"""Geocoding endpoints for Art Basel backend"""

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


GOOGLE_PLACES_AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
GOOGLE_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

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
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Fetch coordinates and first photo for a place. Returns (lat, lng, photo_url)"""
    params = {
        "place_id": place_id,
        "key": api_key,
        "fields": "geometry,photos"  # Only fetch what we need
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

            # Get first photo URL
            photo_url = None
            photos = result.get("photos", [])
            if photos:
                photo_ref = photos[0].get("photo_reference")
                if photo_ref:
                    photo_url = (
                        f"https://maps.googleapis.com/maps/api/place/photo"
                        f"?maxwidth=100"  # Small thumbnail for list
                        f"&photo_reference={photo_ref}"
                        f"&key={api_key}"
                    )

            return lat, lng, photo_url
    except Exception:
        return None, None, None


@router.get("/places/autocomplete", response_model=AutocompleteResponse)
async def places_autocomplete(
    query: str = Query(..., min_length=2, description="Search query"),
    lat: Optional[float] = Query(None, ge=-90, le=90, description="User latitude for location bias"),
    lng: Optional[float] = Query(None, ge=-180, le=180, description="User longitude for location bias"),
    current_user: User = Depends(get_current_user)
):
    """
    Google Places Autocomplete for venue search.

    Returns place predictions with coordinates, distance, and photo.
    Results are sorted by distance (closest first) when lat/lng provided.

    Example: /geocoding/places/autocomplete?query=hooters&lat=25.79&lng=-80.13
    """
    if not settings.GOOGLE_MAPS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Places API not configured. GOOGLE_MAPS_API_KEY required."
        )

    params = {
        "input": query,
        "key": settings.GOOGLE_MAPS_API_KEY,
        "types": "establishment",  # Focus on businesses/venues
    }

    # Add location bias - smaller radius = stronger preference for nearby results
    if lat is not None and lng is not None:
        params["location"] = f"{lat},{lng}"
        params["radius"] = "2000"  # 2km - tight bias for strong local preference

    try:
        ssl_ctx = get_ssl_context()
        async with aiohttp.ClientSession() as session:
            # First, get autocomplete predictions
            async with session.get(GOOGLE_PLACES_AUTOCOMPLETE_URL, params=params, ssl=ssl_ctx) as response:
                data = await response.json()

                if data.get("status") not in ("OK", "ZERO_RESULTS"):
                    raise HTTPException(
                        status_code=502,
                        detail=f"Places API error: {data.get('status')}"
                    )

                raw_predictions = data.get("predictions", [])

                if not raw_predictions:
                    return AutocompleteResponse(predictions=[])

                # Fetch details for all predictions in parallel
                detail_tasks = [
                    fetch_place_details_for_autocomplete(
                        session, pred["place_id"], ssl_ctx, settings.GOOGLE_MAPS_API_KEY
                    )
                    for pred in raw_predictions
                ]
                details_results = await asyncio.gather(*detail_tasks)

                # Build predictions with coordinates and distance
                predictions = []
                for pred, (place_lat, place_lng, photo_url) in zip(raw_predictions, details_results):
                    structured = pred.get("structured_formatting", {})

                    # Calculate distance if we have both user location and place location
                    distance_meters = None
                    if lat is not None and lng is not None and place_lat is not None and place_lng is not None:
                        distance_meters = haversine_distance_meters(lat, lng, place_lat, place_lng)

                    predictions.append(PlacePrediction(
                        place_id=pred["place_id"],
                        name=structured.get("main_text", pred.get("description", "")),
                        address=structured.get("secondary_text", ""),
                        full_description=pred.get("description", ""),
                        latitude=place_lat,
                        longitude=place_lng,
                        distance_meters=distance_meters,
                        photo_url=photo_url
                    ))

                # Sort by distance (closest first) if distances are available
                predictions.sort(key=lambda p: p.distance_meters if p.distance_meters is not None else float('inf'))

                return AutocompleteResponse(predictions=predictions)

    except aiohttp.ClientError as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Places API: {str(e)}")


GOOGLE_PLACES_PHOTO_URL = "https://maps.googleapis.com/maps/api/place/photo"


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

                return PlaceDetails(
                    place_id=place_id,
                    name=result.get("name", ""),
                    address=result.get("formatted_address", ""),
                    latitude=location.get("lat", 0),
                    longitude=location.get("lng", 0),
                    types=result.get("types", []),
                    photos=photos
                )

    except aiohttp.ClientError as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Places API: {str(e)}")