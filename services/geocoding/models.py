"""Pydantic models for geocoding"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Coordinates(BaseModel):
    """Geographic coordinates"""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees")

    @field_validator("latitude", "longitude")
    @classmethod
    def round_precision(cls, v: float) -> float:
        """Round to 6 decimal places (~11cm precision)"""
        return round(v, 6)


class Address(BaseModel):
    """Structured address components"""

    formatted_address: str
    street_number: str | None = None
    street_name: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    country_code: str | None = None


class LocationResult(BaseModel):
    """Complete geocoding result"""

    coordinates: Coordinates
    address: Address
    place_id: str | None = None
    location_type: str | None = None
    provider: Literal["google", "nominatim"] = "google"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    confidence: float | None = Field(None, ge=0, le=1)


class ReverseGeocodeResult(BaseModel):
    """Reverse geocoding result (coordinates → address)"""

    address: Address
    coordinates: Coordinates
    provider: Literal["google", "nominatim"] = "google"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
