import asyncio
import json
import logging
import ssl
from typing import List, Optional

import aiohttp
import certifi
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_current_user
from core.config import settings
from db.models import User
from services.cache import cache_get, cache_set
from services.places.autocomplete import (
    GEO_INDEX,
    META_PREFIX,
    haversine_distance_meters,
    index_place,
)
from services.redis import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nearby", tags=["nearby"])

# Google Places API
GOOGLE_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

# Category → Google Place types
CATEGORY_MAP = {
    "coffee": ["cafe", "coffee_shop"],
    "drinks": ["bar", "night_club", "wine_bar"],
    "dinner": ["restaurant"],
    "hotel": ["hotel", "lodging"],
    "gym": ["gym", "fitness_center", "yoga_studio"],
}

# Grid-snap for caching (~200m cells)
GRID_SIZE = 0.002
CACHE_TTL = 43200  # 12 hours
MIN_REDIS_RESULTS = 5


def _snap(lat: float, lng: float) -> tuple:
    return (round(lat / GRID_SIZE) * GRID_SIZE, round(lng / GRID_SIZE) * GRID_SIZE)


# --- Models ---

class NearbyPlace(BaseModel):
    place_id: str
    name: str
    address: Optional[str]
    latitude: float
    longitude: float
    distance_meters: int
    category: str
    types: List[str]
    photo_url: Optional[str]
    source: str  # "redis" or "google"


class NearbyResponse(BaseModel):
    places: List[NearbyPlace]
    category: str
    from_cache: bool


# --- Endpoint ---

@router.get("", response_model=NearbyResponse)
async def get_nearby_places(
    lat: float = Query(...),
    lng: float = Query(...),
    category: str = Query(...),
    radius: int = Query(500, ge=50, le=5000),
    current_user: User = Depends(get_current_user),
):
    if category not in CATEGORY_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Valid: {', '.join(CATEGORY_MAP.keys())}",
        )

    google_types = CATEGORY_MAP[category]
    grid_lat, grid_lng = _snap(lat, lng)
    cache_key = f"nearby:{category}:{grid_lat:.4f}:{grid_lng:.4f}"

    # 1. Check result cache
    cached = await cache_get(cache_key, reset_ttl=False)
    if cached is not None:
        return NearbyResponse(places=cached, category=category, from_cache=True)

    # 2. Try Redis geo-index
    places = await _search_redis_geo(lat, lng, radius, google_types, category)

    # 3. Fall back to Google if not enough results
    if len(places) < MIN_REDIS_RESULTS:
        google_places = await _search_google(lat, lng, radius, google_types, category)
        # Merge: keep Google results, deduplicate
        existing_ids = {p.place_id for p in places}
        for gp in google_places:
            if gp.place_id not in existing_ids:
                places.append(gp)

    # Sort by distance
    places.sort(key=lambda p: p.distance_meters)

    # Cache the results
    places_dicts = [p.model_dump() for p in places]
    await cache_set(cache_key, places_dicts, ttl=CACHE_TTL)

    return NearbyResponse(places=places, category=category, from_cache=False)


# --- Redis geo-index search ---

async def _search_redis_geo(
    lat: float, lng: float, radius: int, google_types: list, category: str
) -> List[NearbyPlace]:
    try:
        redis = await get_redis()
        # GEORADIUS returns [(member, distance), ...] with WITHDIST
        results = await redis.georadius(
            GEO_INDEX, lng, lat, radius, unit="m", withdist=True, sort="ASC", count=50
        )

        if not results:
            return []

        # Fetch metadata for all results
        pipe = redis.pipeline()
        place_ids = []
        distances = {}
        for item in results:
            pid = item[0] if isinstance(item, (list, tuple)) else item
            dist = float(item[1]) if isinstance(item, (list, tuple)) and len(item) > 1 else 0
            place_ids.append(pid)
            distances[pid] = int(dist)
            pipe.hgetall(f"{META_PREFIX}{pid}")

        metas = await pipe.execute()

        places = []
        type_set = set(google_types)
        for pid, meta in zip(place_ids, metas):
            if not meta:
                continue
            # Filter by types
            try:
                place_types = json.loads(meta.get("types", "[]"))
            except Exception:
                place_types = []
            if not type_set.intersection(place_types):
                continue

            places.append(NearbyPlace(
                place_id=pid,
                name=meta.get("name", ""),
                address=meta.get("address") or None,
                latitude=float(meta.get("lat", 0)),
                longitude=float(meta.get("lng", 0)),
                distance_meters=distances.get(pid, 0),
                category=category,
                types=place_types,
                photo_url=meta.get("photo_url"),
                source="redis",
            ))

        return places
    except Exception as e:
        logger.error(f"Redis geo search failed: {e}")
        return []


# --- Google Places Nearby Search ---

async def _search_google(
    lat: float, lng: float, radius: int, google_types: list, category: str
) -> List[NearbyPlace]:
    if not settings.GOOGLE_MAPS_API_KEY:
        return []

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.location,places.types,places.photos"
        ),
    }

    body = {
        "includedTypes": google_types,
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(radius),
            }
        },
    }

    try:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GOOGLE_NEARBY_URL, headers=headers, json=body, ssl=ssl_ctx
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Google Nearby Search failed: {resp.status}")
                    return []
                data = await resp.json()

        places = []
        for place in data.get("places", []):
            pid = place.get("id", "")
            if not pid:
                continue

            display_name = place.get("displayName", {}).get("text", "")
            address = place.get("formattedAddress", "")
            location = place.get("location", {})
            place_lat = location.get("latitude")
            place_lng = location.get("longitude")
            place_types = place.get("types", [])

            if place_lat is None or place_lng is None:
                continue

            # Photo URL
            photo_url = None
            photos = place.get("photos", [])
            if photos:
                photo_name = photos[0].get("name")
                if photo_name:
                    photo_url = (
                        f"https://places.googleapis.com/v1/{photo_name}/media"
                        f"?maxWidthPx=800&key={settings.GOOGLE_MAPS_API_KEY}"
                    )

            dist = haversine_distance_meters(lat, lng, place_lat, place_lng)

            places.append(NearbyPlace(
                place_id=pid,
                name=display_name,
                address=address or None,
                latitude=place_lat,
                longitude=place_lng,
                distance_meters=dist,
                category=category,
                types=place_types,
                photo_url=photo_url,
                source="google",
            ))

        # Index to Redis in background
        asyncio.create_task(_index_to_cache(places))

        return places
    except Exception as e:
        logger.error(f"Google Nearby Search error: {e}")
        return []


async def _index_to_cache(places: List[NearbyPlace]):
    for p in places:
        await index_place(
            place_id=p.place_id,
            name=p.name,
            address=p.address or "",
            lat=p.latitude,
            lng=p.longitude,
            types=p.types,
            photo_url=p.photo_url,
        )
