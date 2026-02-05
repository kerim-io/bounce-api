"""
Seed script to pre-populate Redis autocomplete cache with venues from key cities.

Uses Google Places Text Search API to find venues by type, then indexes them
to Redis for fast autocomplete. Run once to populate, then text search code
can be removed from the API.

Run: python scripts/seed_places_cache.py

Optional args:
  --cities miami,basel,london  # Comma-separated list of cities to seed
  --dry-run                    # Print what would be indexed without writing
"""

import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
import ssl
import certifi
from core.config import settings
from services.places.autocomplete import index_place, get_indexed_place_count

# Cities to seed with their center coordinates
CITIES = {
    "miami": {"lat": 25.7617, "lng": -80.1918, "radius": 15000},
    "miami_beach": {"lat": 25.7907, "lng": -80.1300, "radius": 8000},
    "basel": {"lat": 47.5596, "lng": 7.5886, "radius": 10000},
    "london": {"lat": 51.5074, "lng": -0.1278, "radius": 15000},
    "dubai": {"lat": 25.2048, "lng": 55.2708, "radius": 20000},
    "new_york": {"lat": 40.7128, "lng": -74.0060, "radius": 15000},
    "los_angeles": {"lat": 34.0522, "lng": -118.2437, "radius": 20000},
    "paris": {"lat": 48.8566, "lng": 2.3522, "radius": 12000},
    "hong_kong": {"lat": 22.3193, "lng": 114.1694, "radius": 12000},
}

# Venue types to search for (these map to Google Places types)
VENUE_QUERIES = [
    "bar",
    "restaurant",
    "cafe",
    "night club",
    "hotel",
    "gym",
    "spa",
    "rooftop bar",
    "cocktail bar",
    "wine bar",
    "lounge",
    "beach club",
    "members club",
    "private club",
    "fine dining",
    "brunch",
]

GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


def get_ssl_context():
    return ssl.create_default_context(cafile=certifi.where())


async def text_search_places(
    session: aiohttp.ClientSession,
    query: str,
    lat: float,
    lng: float,
    radius: float,
    ssl_ctx,
    api_key: str,
) -> list[dict]:
    """
    Search for places using Google Text Search API.
    Returns list of place dicts ready for indexing.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.types,places.photos",
    }

    body = {
        "textQuery": query,
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(radius),
            }
        },
        "maxResultCount": 20,
    }

    try:
        async with session.post(
            GOOGLE_PLACES_TEXT_SEARCH_URL,
            headers=headers,
            json=body,
            ssl=ssl_ctx
        ) as resp:
            if resp.status != 200:
                error = await resp.text()
                print(f"    API error ({resp.status}): {error[:200]}")
                return []

            data = await resp.json()
            places = []

            for place in data.get("places", []):
                place_id = place.get("id", "")
                if not place_id:
                    continue

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
                            f"?maxWidthPx=800&key={api_key}"
                        )

                if place_lat is not None and place_lng is not None:
                    places.append({
                        "place_id": place_id,
                        "name": display_name,
                        "address": address,
                        "lat": place_lat,
                        "lng": place_lng,
                        "types": place_types,
                        "photo_url": photo_url,
                    })

            return places

    except Exception as e:
        print(f"    Error: {e}")
        return []


async def seed_city(
    session: aiohttp.ClientSession,
    city_name: str,
    city_config: dict,
    ssl_ctx,
    api_key: str,
    dry_run: bool = False,
) -> int:
    """Seed all venue types for a single city. Returns count of places indexed."""
    print(f"\n{'='*50}")
    print(f"Seeding {city_name.upper()}")
    print(f"  Center: {city_config['lat']}, {city_config['lng']}")
    print(f"  Radius: {city_config['radius']}m")
    print(f"{'='*50}")

    total_indexed = 0
    seen_place_ids = set()

    for query in VENUE_QUERIES:
        search_query = f"{query} in {city_name.replace('_', ' ')}"
        print(f"\n  Searching: '{search_query}'")

        places = await text_search_places(
            session,
            search_query,
            city_config["lat"],
            city_config["lng"],
            city_config["radius"],
            ssl_ctx,
            api_key,
        )

        new_places = 0
        for place in places:
            if place["place_id"] in seen_place_ids:
                continue
            seen_place_ids.add(place["place_id"])

            if dry_run:
                print(f"    [DRY RUN] Would index: {place['name']}")
                new_places += 1
            else:
                success = await index_place(
                    place_id=place["place_id"],
                    name=place["name"],
                    address=place["address"],
                    lat=place["lat"],
                    lng=place["lng"],
                    types=place["types"],
                    bounce_count=0,
                    photo_url=place["photo_url"],
                )
                if success:
                    print(f"    Indexed: {place['name']}")
                    new_places += 1
                else:
                    print(f"    Failed: {place['name']}")

        total_indexed += new_places
        print(f"    Found {len(places)} places, {new_places} new")

        # Rate limit
        await asyncio.sleep(0.2)

    return total_indexed


async def main():
    parser = argparse.ArgumentParser(description="Seed Redis places cache")
    parser.add_argument(
        "--cities",
        type=str,
        default=None,
        help="Comma-separated list of cities (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be indexed without writing",
    )
    args = parser.parse_args()

    api_key = settings.GOOGLE_MAPS_API_KEY
    if not api_key:
        print("ERROR: GOOGLE_MAPS_API_KEY not set")
        sys.exit(1)

    # Determine which cities to seed
    if args.cities:
        city_names = [c.strip().lower() for c in args.cities.split(",")]
        cities_to_seed = {k: v for k, v in CITIES.items() if k in city_names}
        unknown = set(city_names) - set(CITIES.keys())
        if unknown:
            print(f"WARNING: Unknown cities ignored: {unknown}")
            print(f"Available: {list(CITIES.keys())}")
    else:
        cities_to_seed = CITIES

    if not cities_to_seed:
        print("ERROR: No valid cities to seed")
        sys.exit(1)

    print("=" * 60)
    print("PLACES CACHE SEEDER")
    print("=" * 60)
    print(f"Cities: {list(cities_to_seed.keys())}")
    print(f"Venue queries: {len(VENUE_QUERIES)}")
    print(f"Dry run: {args.dry_run}")

    if not args.dry_run:
        count_before = await get_indexed_place_count()
        print(f"Places in cache before: {count_before}")

    ssl_ctx = get_ssl_context()
    total = 0

    async with aiohttp.ClientSession() as session:
        for city_name, city_config in cities_to_seed.items():
            count = await seed_city(
                session, city_name, city_config, ssl_ctx, api_key, args.dry_run
            )
            total += count

    print("\n" + "=" * 60)
    print("SEEDING COMPLETE")
    print("=" * 60)
    print(f"Total places indexed: {total}")

    if not args.dry_run:
        count_after = await get_indexed_place_count()
        print(f"Places in cache after: {count_after}")
        print(f"Net new places: {count_after - count_before}")


if __name__ == "__main__":
    asyncio.run(main())
