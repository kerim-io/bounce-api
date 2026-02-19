"""Geocoding endpoints for Art Basel backend"""

import asyncio
from typing import List, Optional
import aiohttp
import ssl
import certifi

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.geocoding import GeocodingService, LocationResult, ReverseGeocodeResult
from api.dependencies import get_current_user
from db.models import User
from core.config import settings
from services.cache import cache_get, cache_set
from services.places.autocomplete import (
    global_autocomplete_search,
    index_place as index_place_to_cache
)

router = APIRouter(prefix="/geocoding", tags=["geocoding"])

# Global geocoding service (initialized on startup)
_geocoding_service = None


def get_geocoding_service() -> GeocodingService:
    """Get geocoding service instance"""
    global _geocoding_service
    if _geocoding_service is None:
        if not settings.GOOGLE_MAPS_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="Geocoding service not configured. GOOGLE_MAPS_API_KEY required."
            )
        _geocoding_service = GeocodingService(google_api_key=settings.GOOGLE_MAPS_API_KEY)
    return _geocoding_service


class GeocodeRequest(BaseModel):
    """Request to geocode an address"""
    address: str = Field(..., description="Address to geocode", min_length=1)


class ReverseGeocodeRequest(BaseModel):
    """Request to reverse geocode coordinates"""
    latitude: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees")


@router.post("/forward", response_model=LocationResult)
async def geocode_address(
    request: GeocodeRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Forward geocoding: Convert address to coordinates

    Requires authentication with Apple Sign In.

    Example: {"address": "Miami Beach Convention Center, Miami Beach, FL"}
    """
    service = get_geocoding_service()
    result = service.geocode(request.address)

    if not result:
        raise HTTPException(status_code=404, detail="Address not found")

    return result


@router.get("/forward", response_model=LocationResult)
async def geocode_address_get(
    address: str = Query(..., description="Address to geocode", min_length=1),
    current_user: User = Depends(get_current_user)
):
    """
    Forward geocoding: Convert address to coordinates (GET method)

    Requires authentication with Apple Sign In.

    Example: /geocoding/forward?address=Miami%20Beach%20Convention%20Center
    """
    service = get_geocoding_service()
    result = service.geocode(address)

    if not result:
        raise HTTPException(status_code=404, detail="Address not found")

    return result


@router.post("/reverse", response_model=ReverseGeocodeResult)
async def reverse_geocode(
    request: ReverseGeocodeRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Reverse geocoding: Convert coordinates to address

    Requires authentication with Apple Sign In.

    Example: {"latitude": 25.7907, "longitude": -80.1300}
    """
    service = get_geocoding_service()
    result = service.reverse_geocode(request.latitude, request.longitude)

    if not result:
        raise HTTPException(status_code=404, detail="Location not found")

    return result


@router.get("/reverse", response_model=ReverseGeocodeResult)
async def reverse_geocode_get(
    lat: float = Query(..., ge=-90, le=90, description="Latitude in decimal degrees"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude in decimal degrees"),
    current_user: User = Depends(get_current_user)
):
    """
    Reverse geocoding: Convert coordinates to address (GET method)

    Requires authentication with Apple Sign In.

    Example: /geocoding/reverse?lat=25.7907&lon=-80.1300
    """
    service = get_geocoding_service()
    result = service.reverse_geocode(lat, lon)

    if not result:
        raise HTTPException(status_code=404, detail="Location not found")

    return result


# ============== Places Autocomplete ==============

class PlacePrediction(BaseModel):
    """A single place prediction from autocomplete"""
    place_id: str
    name: str  # Main text (e.g., "Wynwood Walls")
    address: str  # Secondary text (e.g., "Miami, FL, USA")
    full_description: str  # Combined description
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_meters: Optional[int] = None  # Distance from user in meters
    photo_url: Optional[str] = None  # First photo URL
    types: List[str] = []  # Venue types (bar, restaurant, cafe, etc.)
    from_cache: bool = False  # True if from Redis cache, False if from Google API


class PlacePhoto(BaseModel):
    """A photo for a place"""
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


class PlaceDetails(BaseModel):
    """Detailed place information including coordinates and photos"""
    place_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    types: List[str] = []
    photos: List[PlacePhoto] = []


class AutocompleteResponse(BaseModel):
    """Response from places autocomplete"""
    predictions: List[PlacePrediction]
    from_cache: bool = False


GOOGLE_PLACES_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Place types for venues (max 5 per Google Places API request)
VENUE_TYPES_A = [
    "restaurant",
    "bar",
    "cafe",
    "night_club",
    "hotel",
]
VENUE_TYPES_B = [
    "gym",
    "yoga_studio",
]

# SSL context for aiohttp requests to Google APIs
def get_ssl_context():
    return ssl.create_default_context(cafile=certifi.where())


import math
import asyncio

def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Calculate distance between two points in meters using Haversine formula"""
    R = 6371000  # Earth's radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return int(R * c)


async def fetch_place_details_for_autocomplete(
    session: aiohttp.ClientSession,
    place_id: str,
    ssl_ctx,
    api_key: str
) -> tuple[Optional[float], Optional[float], Optional[str], List[str]]:
    """Fetch coordinates, photo, and types for a place. Returns (lat, lng, photo_url, types).

    Uses cache to avoid redundant API calls - popular places are fetched once
    and reused across all users' searches.
    """
    # Check cache first - reuse place details across all searches
    cache_key = f"place_details:{place_id}"
    cached = await cache_get(cache_key)
    if cached:
        lat = cached.get("latitude")
        lng = cached.get("longitude")
        photos = cached.get("photos", [])
        photo_url = photos[0].get("url") if photos else None
        types = cached.get("types", [])
        return lat, lng, photo_url, types

    params = {
        "place_id": place_id,
        "key": api_key,
        "fields": "name,formatted_address,geometry,types,photos"  # Fetch full details for caching
    }

    try:
        async with session.get(GOOGLE_PLACES_DETAILS_URL, params=params, ssl=ssl_ctx) as response:
            data = await response.json()

            if data.get("status") != "OK":
                return None, None, None

            result = data.get("result", {})
            location = result.get("geometry", {}).get("location", {})
            lat = location.get("lat")
            lng = location.get("lng")

            # Build photo URLs (up to 5 photos) for caching
            photos = []
            for photo in result.get("photos", [])[:5]:
                photo_ref = photo.get("photo_reference")
                if photo_ref:
                    photo_url = (
                        f"https://maps.googleapis.com/maps/api/place/photo"
                        f"?maxwidth=800"
                        f"&photo_reference={photo_ref}"
                        f"&key={api_key}"
                    )
                    photos.append({
                        "url": photo_url,
                        "width": photo.get("width"),
                        "height": photo.get("height")
                    })

            # Cache full place details for 24 hours (reused by /places/details endpoint too)
            types = result.get("types", [])
            place_details = {
                "place_id": place_id,
                "name": result.get("name", ""),
                "address": result.get("formatted_address", ""),
                "latitude": lat,
                "longitude": lng,
                "types": types,
                "photos": photos
            }
            await cache_set(cache_key, place_details)

            # Also index to autocomplete so this place is searchable
            await index_place_to_cache(
                place_id=place_id,
                name=place_details["name"],
                address=place_details["address"],
                lat=lat,
                lng=lng,
                types=types,
                bounce_count=0,
                photo_url=photos[0]["url"] if photos else None,
            )

            # Return first photo URL for autocomplete thumbnail
            first_photo_url = photos[0]["url"] if photos else None
            return lat, lng, first_photo_url, types
    except Exception:
        return None, None, None, []


async def _index_predictions_to_global_cache(predictions: List[PlacePrediction]) -> None:
    """Fire-and-forget: index Google API predictions to global cache."""
    for pred in predictions:
        if pred.place_id and pred.name and pred.latitude and pred.longitude:
            await index_place_to_cache(
                place_id=pred.place_id,
                name=pred.name,
                address=pred.address or "",
                lat=pred.latitude,
                lng=pred.longitude,
                types=pred.types,
                bounce_count=0,
                photo_url=pred.photo_url
            )


@router.get("/places/autocomplete", response_model=AutocompleteResponse)
async def places_autocomplete(
    query: str = Query(..., min_length=2, description="Search query"),
    lat: Optional[float] = Query(None, ge=-90, le=90, description="User latitude for location bias"),
    lng: Optional[float] = Query(None, ge=-180, le=180, description="User longitude for location bias"),
    current_user: User = Depends(get_current_user)
):
    """
    Places Autocomplete for venue search (bars, restaurants, cafes, clubs).

    Searches global Redis cache first for instant results, falls back to Google API.
    Global cache enables cross-location discovery (London user finds Munich venues).

    Example: /geocoding/places/autocomplete?query=hooters&lat=25.79&lng=-80.13
    """
    # 1. Search global cache FIRST (location-independent)
    cached_results, cache_hit = await global_autocomplete_search(
        query=query,
        user_lat=lat,
        user_lng=lng,
        limit=10
    )

    # 2. If we have any cached results, return them immediately (avoid hitting Places API)
    if cached_results:
        predictions = [PlacePrediction(**{**p, "from_cache": True}) for p in cached_results]
        return AutocompleteResponse(predictions=predictions, from_cache=True)

    # 3. Fall back to Google API (only when Redis has no matches)
    if not settings.GOOGLE_MAPS_API_KEY:
        # If no API key, return whatever we have from cache
        if cached_results:
            predictions = [PlacePrediction(**{**p, "from_cache": True}) for p in cached_results]
            return AutocompleteResponse(predictions=predictions, from_cache=True)
        raise HTTPException(
            status_code=503,
            detail="Places API not configured. GOOGLE_MAPS_API_KEY required."
        )

    # New Places API uses POST with JSON body
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
    }

    location_bias = None
    if lat is not None and lng is not None:
        location_bias = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": 5000.0  # 5km bias
            }
        }

    # Build two autocomplete request bodies — one per type batch (API max 5 types).
    ac_bodies = []
    for type_batch in [VENUE_TYPES_A, VENUE_TYPES_B]:
        b = {"input": query, "includedPrimaryTypes": type_batch}
        if location_bias:
            b["locationBias"] = location_bias
        ac_bodies.append(b)

    async def _autocomplete_request(session, body, ssl_ctx):
        """Fire one autocomplete request, return suggestions list or []."""
        try:
            async with session.post(GOOGLE_PLACES_AUTOCOMPLETE_URL, headers=headers, json=body, ssl=ssl_ctx) as resp:
                data = await resp.json()
                if resp.status != 200:
                    return []
                return data.get("suggestions", [])
        except Exception:
            return []

    async def _text_search_request(session, ssl_ctx):
        """Fire a text search request (no type filter) to catch places autocomplete misses."""
        try:
            ts_headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.photos",
            }
            body = {"textQuery": query, "maxResultCount": 5}
            if location_bias:
                body["locationBias"] = location_bias
            async with session.post(GOOGLE_PLACES_TEXT_SEARCH_URL, headers=ts_headers, json=body, ssl=ssl_ctx) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("places", [])
        except Exception:
            return []

    try:
        ssl_ctx = get_ssl_context()
        async with aiohttp.ClientSession() as session:
            # Fire two typed autocomplete batches + one text search in parallel
            results_a, results_b, text_results = await asyncio.gather(
                _autocomplete_request(session, ac_bodies[0], ssl_ctx),
                _autocomplete_request(session, ac_bodies[1], ssl_ctx),
                _text_search_request(session, ssl_ctx),
            )

            # Merge and deduplicate autocomplete suggestions (typed results first)
            seen_ids = set()
            raw_predictions = []
            for pred in results_a + results_b:
                pid = pred.get("placePrediction", {}).get("placeId")
                if pid and pid not in seen_ids:
                    raw_predictions.append(pred)
                    seen_ids.add(pid)

            if not raw_predictions:
                if cached_results:
                    predictions = [PlacePrediction(**{**p, "from_cache": True}) for p in cached_results]
                    return AutocompleteResponse(predictions=predictions, from_cache=True)
                return AutocompleteResponse(predictions=[])

            # Fetch details for all predictions in parallel
            detail_tasks = [
                fetch_place_details_for_autocomplete(
                    session,
                    pred.get("placePrediction", {}).get("placeId", ""),
                    ssl_ctx,
                    settings.GOOGLE_MAPS_API_KEY
                )
                for pred in raw_predictions
                if pred.get("placePrediction")
            ]
            details_results = await asyncio.gather(*detail_tasks)

            # Build predictions with coordinates and distance
            google_predictions = []
            detail_idx = 0
            for pred in raw_predictions:
                place_pred = pred.get("placePrediction")
                if not place_pred:
                    continue

                place_lat, place_lng, photo_url, place_types = details_results[detail_idx]
                detail_idx += 1

                # Calculate distance if we have both user location and place location
                distance_meters = None
                if lat is not None and lng is not None and place_lat is not None and place_lng is not None:
                    distance_meters = haversine_distance_meters(lat, lng, place_lat, place_lng)

                # Extract structured text from new API format
                structured_format = place_pred.get("structuredFormat", {})
                main_text = structured_format.get("mainText", {}).get("text", "")
                secondary_text = structured_format.get("secondaryText", {}).get("text", "")

                google_predictions.append(PlacePrediction(
                    place_id=place_pred.get("placeId", ""),
                    name=main_text or place_pred.get("text", {}).get("text", ""),
                    address=secondary_text,
                    full_description=place_pred.get("text", {}).get("text", ""),
                    latitude=place_lat,
                    longitude=place_lng,
                    distance_meters=distance_meters,
                    photo_url=photo_url,
                    types=place_types or [],
                    from_cache=False,
                ))

            # 4. Merge cached results with Google results (cached first, deduped)
            seen_place_ids = set()
            merged_predictions = []

            # Add cached results first (they have bounce_count scoring)
            for cached in cached_results:
                pid = cached.get("place_id")
                if pid and pid not in seen_place_ids:
                    merged_predictions.append(PlacePrediction(**{**cached, "from_cache": True}))
                    seen_place_ids.add(pid)

            # Add autocomplete results (skip duplicates)
            for gp in google_predictions:
                if gp.place_id not in seen_place_ids:
                    merged_predictions.append(gp)
                    seen_place_ids.add(gp.place_id)

            # Add text search results (catches places autocomplete misses)
            for place in text_results:
                pid = place.get("id", "")
                if not pid or pid in seen_place_ids:
                    continue
                seen_place_ids.add(pid)

                display_name = place.get("displayName", {}).get("text", "")
                address = place.get("formattedAddress", "")
                location = place.get("location", {})
                place_lat = location.get("latitude")
                place_lng = location.get("longitude")
                place_types = place.get("types", [])

                # Build photo URL from first photo
                photo_url = None
                photos = place.get("photos", [])
                if photos:
                    photo_name = photos[0].get("name")
                    if photo_name:
                        photo_url = (
                            f"https://places.googleapis.com/v1/{photo_name}/media"
                            f"?maxWidthPx=800&key={settings.GOOGLE_MAPS_API_KEY}"
                        )

                distance_meters = None
                if lat is not None and lng is not None and place_lat is not None and place_lng is not None:
                    distance_meters = haversine_distance_meters(lat, lng, place_lat, place_lng)

                merged_predictions.append(PlacePrediction(
                    place_id=pid,
                    name=display_name,
                    address=address,
                    full_description=f"{display_name} - {address}" if address else display_name,
                    latitude=place_lat,
                    longitude=place_lng,
                    distance_meters=distance_meters,
                    photo_url=photo_url,
                    types=place_types,
                    from_cache=False,
                ))

            # Sort by distance (closest first) if distances are available
            merged_predictions.sort(key=lambda p: p.distance_meters if p.distance_meters is not None else float('inf'))

            # Limit to 10 results
            final_predictions = merged_predictions[:10]

            # 5. Index all Google results to global cache (fire-and-forget)
            all_google_predictions = google_predictions + [
                p for p in merged_predictions
                if not p.from_cache and p.place_id not in {gp.place_id for gp in google_predictions}
            ]
            asyncio.create_task(_index_predictions_to_global_cache(all_google_predictions))

            return AutocompleteResponse(
                predictions=final_predictions,
                from_cache=len(cached_results) > 0 and len(google_predictions) == 0
            )

    except aiohttp.ClientError as e:
        # If network fails but we have cache results, return those
        if cached_results:
            predictions = [PlacePrediction(**{**p, "from_cache": True}) for p in cached_results]
            return AutocompleteResponse(predictions=predictions, from_cache=True)
        raise HTTPException(status_code=502, detail=f"Failed to reach Places API: {str(e)}")


GOOGLE_PLACES_PHOTO_URL = "https://maps.googleapis.com/maps/api/place/photo"


@router.get("/places/textsearch", response_model=AutocompleteResponse)
async def places_text_search(
    query: str = Query(..., min_length=2, description="Search query"),
    lat: Optional[float] = Query(None, ge=-90, le=90, description="User latitude for location bias"),
    lng: Optional[float] = Query(None, ge=-180, le=180, description="User longitude for location bias"),
    current_user: User = Depends(get_current_user)
):
    """
    Text Search for places — no type filter, finds anything by name or category.

    Use this for "Search nearby" when the user wants to find places that don't
    match standard venue types (e.g. "members clubs", "Annabel's").

    Returns same format as autocomplete for client reuse.

    Example: /geocoding/places/textsearch?query=members+clubs&lat=51.50&lng=-0.12
    """
    if not settings.GOOGLE_MAPS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Places API not configured. GOOGLE_MAPS_API_KEY required."
        )

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.photos",
    }

    body = {"textQuery": query, "maxResultCount": 10}
    if lat is not None and lng is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": 5000.0,
            }
        }

    try:
        ssl_ctx = get_ssl_context()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GOOGLE_PLACES_TEXT_SEARCH_URL, headers=headers, json=body, ssl=ssl_ctx
            ) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=502, detail="Text Search API error")
                data = await resp.json()

            predictions = []
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

                photo_url = None
                photos = place.get("photos", [])
                if photos:
                    photo_name = photos[0].get("name")
                    if photo_name:
                        photo_url = (
                            f"https://places.googleapis.com/v1/{photo_name}/media"
                            f"?maxWidthPx=800&key={settings.GOOGLE_MAPS_API_KEY}"
                        )

                distance_meters = None
                if lat is not None and lng is not None and place_lat is not None and place_lng is not None:
                    distance_meters = haversine_distance_meters(lat, lng, place_lat, place_lng)

                predictions.append(PlacePrediction(
                    place_id=pid,
                    name=display_name,
                    address=address,
                    full_description=f"{display_name} - {address}" if address else display_name,
                    latitude=place_lat,
                    longitude=place_lng,
                    distance_meters=distance_meters,
                    photo_url=photo_url,
                    types=place_types,
                    from_cache=False,
                ))

            # Sort by distance
            predictions.sort(key=lambda p: p.distance_meters if p.distance_meters is not None else float('inf'))

            # Index to cache for future autocomplete hits
            asyncio.create_task(_index_predictions_to_global_cache(predictions))

            return AutocompleteResponse(predictions=predictions, from_cache=False)

    except aiohttp.ClientError as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Text Search API: {str(e)}")


@router.get("/places/details/{place_id}", response_model=PlaceDetails)
async def get_place_details(
    place_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get full details for a place including coordinates and photos.

    Call this after user selects a place from autocomplete to get lat/lng and photos.

    Example: /geocoding/places/details/ChIJN1t_tDeuEmsRUsoyG83frY4
    """
    # Check cache first (place details rarely change)
    cache_key = f"place_details:{place_id}"
    cached = await cache_get(cache_key)
    if cached:
        return PlaceDetails(**cached)

    if not settings.GOOGLE_MAPS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Places API not configured. GOOGLE_MAPS_API_KEY required."
        )

    params = {
        "place_id": place_id,
        "key": settings.GOOGLE_MAPS_API_KEY,
        "fields": "name,formatted_address,geometry,types,photos"
    }

    try:
        ssl_ctx = get_ssl_context()
        async with aiohttp.ClientSession() as session:
            async with session.get(GOOGLE_PLACES_DETAILS_URL, params=params, ssl=ssl_ctx) as response:
                data = await response.json()

                if data.get("status") != "OK":
                    raise HTTPException(
                        status_code=404 if data.get("status") == "NOT_FOUND" else 502,
                        detail=f"Place not found or API error: {data.get('status')}"
                    )

                result = data.get("result", {})
                location = result.get("geometry", {}).get("location", {})

                # Build photo URLs (up to 5 photos)
                photos = []
                for photo in result.get("photos", [])[:5]:
                    photo_ref = photo.get("photo_reference")
                    if photo_ref:
                        photo_url = (
                            f"{GOOGLE_PLACES_PHOTO_URL}"
                            f"?maxwidth=800"
                            f"&photo_reference={photo_ref}"
                            f"&key={settings.GOOGLE_MAPS_API_KEY}"
                        )
                        photos.append(PlacePhoto(
                            url=photo_url,
                            width=photo.get("width"),
                            height=photo.get("height")
                        ))

                place_details = PlaceDetails(
                    place_id=place_id,
                    name=result.get("name", ""),
                    address=result.get("formatted_address", ""),
                    latitude=location.get("lat", 0),
                    longitude=location.get("lng", 0),
                    types=result.get("types", []),
                    photos=photos
                )

                # Cache for 24 hours (place details rarely change)
                await cache_set(cache_key, place_details.model_dump())

                # Also index to autocomplete so this place is searchable
                await index_place_to_cache(
                    place_id=place_id,
                    name=place_details.name,
                    address=place_details.address,
                    lat=place_details.latitude,
                    lng=place_details.longitude,
                    types=place_details.types,
                    bounce_count=0,
                    photo_url=photos[0].url if photos else None,
                )

                return place_details

    except aiohttp.ClientError as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Places API: {str(e)}")