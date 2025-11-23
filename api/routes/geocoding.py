"""Geocoding endpoints for Art Basel backend"""

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