"""Geocoding service using Google Maps API"""

import os

from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import GoogleV3

from .models import Address, Coordinates, LocationResult, ReverseGeocodeResult


class GeocodingService:
    """
    Production geocoding service using Google Maps API
    """

    def __init__(
        self,
        google_api_key: str | None = None,
        timeout: int = 10,
    ):
        """
        Initialize geocoding service

        Args:
            google_api_key: Google Maps API key (or set GOOGLE_MAPS_API_KEY env var)
            timeout: Request timeout in seconds
        """
        self.timeout = timeout

        api_key = google_api_key or os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            raise ValueError(
                "Google Maps API key required. Set GOOGLE_MAPS_API_KEY "
                "environment variable or pass google_api_key parameter"
            )
        self.geocoder = GoogleV3(api_key=api_key, timeout=timeout)
        self.provider = "google"

    def geocode(self, address: str, exactly_one: bool = True) -> LocationResult | None:
        """
        Convert address to coordinates (forward geocoding)

        Args:
            address: Address string to geocode
            exactly_one: Return only best match

        Returns:
            LocationResult with coordinates and parsed address
        """
        try:
            location = self.geocoder.geocode(address, exactly_one=exactly_one, timeout=self.timeout)

            if not location:
                return None

            # Parse address components from Google
            address_obj = self._parse_google_address(location)

            return LocationResult(
                coordinates=Coordinates(
                    latitude=location.latitude,
                    longitude=location.longitude,
                ),
                address=address_obj,
                place_id=getattr(location.raw, "place_id", None),
                location_type=self._get_location_type(location),
                provider=self.provider,
            )

        except (GeocoderTimedOut, GeocoderServiceError) as e:
            print(f"Geocoding error: {e}")
            return None

    def reverse_geocode(self, latitude: float, longitude: float) -> ReverseGeocodeResult | None:
        """
        Convert coordinates to address (reverse geocoding)

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees

        Returns:
            ReverseGeocodeResult with address information
        """
        try:
            coords = Coordinates(latitude=latitude, longitude=longitude)
            location = self.geocoder.reverse(
                f"{coords.latitude}, {coords.longitude}",
                exactly_one=True,
                timeout=self.timeout,
            )

            if not location:
                return None

            address_obj = self._parse_google_address(location)

            return ReverseGeocodeResult(
                address=address_obj,
                coordinates=coords,
                provider=self.provider,
            )

        except (GeocoderTimedOut, GeocoderServiceError) as e:
            print(f"Reverse geocoding error: {e}")
            return None

    def _parse_google_address(self, location) -> Address:
        """Parse Google Maps API response into Address model"""
        raw = location.raw
        components = {}

        # Extract address components from Google response
        if "address_components" in raw:
            for component in raw["address_components"]:
                types = component.get("types", [])
                if "street_number" in types:
                    components["street_number"] = component["long_name"]
                elif "route" in types:
                    components["street_name"] = component["long_name"]
                elif "locality" in types:
                    components["city"] = component["long_name"]
                elif "administrative_area_level_1" in types:
                    components["state"] = component["short_name"]
                elif "postal_code" in types:
                    components["postal_code"] = component["long_name"]
                elif "country" in types:
                    components["country"] = component["long_name"]
                    components["country_code"] = component["short_name"]

        return Address(
            formatted_address=raw.get("formatted_address", location.address),
            **components,
        )

    def _get_location_type(self, location) -> str | None:
        """Extract location type/precision indicator from Google"""
        return location.raw.get("geometry", {}).get("location_type")
