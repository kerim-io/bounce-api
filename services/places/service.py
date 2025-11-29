"""
Places service for fetching and storing Google Places data.
Handles deduplication and photo fetching.
"""

import json
import logging
import ssl
import certifi
from typing import Optional, List

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.models import Place, GooglePic

logger = logging.getLogger(__name__)

GOOGLE_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
GOOGLE_PLACES_PHOTO_URL = "https://maps.googleapis.com/maps/api/place/photo"

MAX_PHOTOS = 5


def get_ssl_context():
    """Get SSL context for aiohttp requests"""
    return ssl.create_default_context(cafile=certifi.where())


class PlacesService:
    """Service for managing Google Places data"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_place_details_with_photos(self, google_place_id: str) -> Optional[dict]:
        """
        Fetch place details including photo references from Google Places API.

        Returns dict with:
        - name, address, latitude, longitude, types
        - photos: list of photo references (up to 5)
        """
        params = {
            "place_id": google_place_id,
            "key": self.api_key,
            "fields": "name,formatted_address,geometry,types,photos"
        }

        try:
            ssl_ctx = get_ssl_context()
            async with aiohttp.ClientSession() as session:
                async with session.get(GOOGLE_PLACES_DETAILS_URL, params=params, ssl=ssl_ctx) as response:
                    data = await response.json()

                    if data.get("status") != "OK":
                        logger.error(f"Places API error for {google_place_id}: {data.get('status')}")
                        return None

                    result = data.get("result", {})
                    location = result.get("geometry", {}).get("location", {})

                    # Extract photo references (up to MAX_PHOTOS)
                    photos = []
                    for photo in result.get("photos", [])[:MAX_PHOTOS]:
                        photos.append({
                            "photo_reference": photo.get("photo_reference"),
                            "width": photo.get("width"),
                            "height": photo.get("height"),
                            "attributions": photo.get("html_attributions", [])
                        })

                    return {
                        "name": result.get("name", ""),
                        "address": result.get("formatted_address", ""),
                        "latitude": location.get("lat", 0),
                        "longitude": location.get("lng", 0),
                        "types": result.get("types", []),
                        "photos": photos
                    }

        except aiohttp.ClientError as e:
            logger.error(f"Failed to fetch place details: {e}")
            return None

    def get_photo_url(self, photo_reference: str, max_width: int = 800) -> str:
        """
        Generate a Google Places photo URL from a photo reference.

        Note: These URLs require the API key and will redirect to the actual image.
        """
        return (
            f"{GOOGLE_PLACES_PHOTO_URL}"
            f"?maxwidth={max_width}"
            f"&photo_reference={photo_reference}"
            f"&key={self.api_key}"
        )


async def get_place_with_photos(
    db: AsyncSession,
    google_place_id: str,
    venue_name: str,
    venue_address: Optional[str],
    latitude: float,
    longitude: float,
    source: str = "bounce"
) -> Optional[Place]:
    """
    Get or create a Place record with photos.

    If the place already exists (by google_place_id), increments the appropriate count and returns it.
    If it doesn't exist, fetches details and photos from Google, stores them, and returns the new Place.

    Args:
        db: Database session
        google_place_id: Google's place_id
        venue_name: Venue name (fallback if API fails)
        venue_address: Venue address (fallback if API fails)
        latitude: Latitude (fallback if API fails)
        longitude: Longitude (fallback if API fails)
        source: "bounce" or "post" - determines which count to increment

    Returns:
        Place object or None if creation failed
    """
    if not google_place_id:
        logger.warning("No google_place_id provided, cannot store place")
        return None

    # Check if place already exists
    result = await db.execute(
        select(Place).where(Place.google_place_id == google_place_id)
    )
    existing_place = result.scalar_one_or_none()

    if existing_place:
        # Increment the appropriate count
        if source == "post":
            existing_place.post_count += 1
            logger.info(f"Place {google_place_id} already exists, post_count now {existing_place.post_count}")
        else:
            existing_place.bounce_count += 1
            logger.info(f"Place {google_place_id} already exists, bounce_count now {existing_place.bounce_count}")
        await db.flush()
        return existing_place

    # Place doesn't exist - fetch from Google and create
    if not settings.GOOGLE_MAPS_API_KEY:
        logger.error("GOOGLE_MAPS_API_KEY not configured")
        return None

    service = PlacesService(settings.GOOGLE_MAPS_API_KEY)
    details = await service.fetch_place_details_with_photos(google_place_id)

    # Set initial counts based on source
    initial_bounce_count = 1 if source == "bounce" else 0
    initial_post_count = 1 if source == "post" else 0

    if details:
        # Use API data
        place = Place(
            google_place_id=google_place_id,
            name=details["name"],
            address=details["address"],
            latitude=details["latitude"],
            longitude=details["longitude"],
            types=json.dumps(details["types"]) if details["types"] else None,
            bounce_count=initial_bounce_count,
            post_count=initial_post_count
        )
    else:
        # Fallback to provided data if API fails
        logger.warning(f"Failed to fetch details for {google_place_id}, using fallback data")
        place = Place(
            google_place_id=google_place_id,
            name=venue_name,
            address=venue_address,
            latitude=latitude,
            longitude=longitude,
            types=None,
            bounce_count=initial_bounce_count,
            post_count=initial_post_count
        )

    db.add(place)
    await db.flush()  # Get the place ID

    # Add photos if we got them from the API
    if details and details.get("photos"):
        for photo_data in details["photos"]:
            photo = GooglePic(
                place_id=place.id,
                photo_reference=photo_data["photo_reference"],
                photo_url=service.get_photo_url(photo_data["photo_reference"]),
                width=photo_data.get("width"),
                height=photo_data.get("height"),
                attributions=json.dumps(photo_data.get("attributions", []))
            )
            db.add(photo)

        logger.info(f"Created place {google_place_id} with {len(details['photos'])} photos")
    else:
        logger.info(f"Created place {google_place_id} without photos")

    await db.flush()
    return place
