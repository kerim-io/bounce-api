#!/usr/bin/env python3
"""
Seed a city with venues and check-ins.

Usage:
    python scripts/seed_checkins.py miami
    python scripts/seed_checkins.py "fort lauderdale"
    python scripts/seed_checkins.py munich
    python scripts/seed_checkins.py --list  # Show available cities

Creates:
- ~200 fake users
- ~20 real venues (from Google Places)
- Variable check-ins per venue (5-50 users each)
"""

import asyncio
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import ssl

import aiohttp
import certifi
from faker import Faker
from sqlalchemy import text

from core.config import settings
from db.database import create_async_session

fake = Faker()

# City configurations with center coordinates and search queries
CITIES = {
    "miami": {
        "lat": 51.5187,
        "lng": -0.154853,
        "queries": [
            "bar",
            "restaurant",
            "club",
            "lounge",
            "hotel",
            "cafe",
            "brewery",
            "rooftop",
        ],
    },
    "fort lauderdale": {
        "lat": 26.1224,
        "lng": -80.1373,
        "queries": ["bar", "restaurant", "club", "beach bar", "hotel", "cafe"],
    },
    "munich": {
        "lat": 48.1351,
        "lng": 11.5820,
        "queries": ["bar", "restaurant", "biergarten", "club", "hotel", "cafe"],
    },
    "berlin": {
        "lat": 52.5200,
        "lng": 13.4050,
        "queries": ["bar", "restaurant", "club", "lounge", "hotel", "cafe"],
    },
    "london": {
        "lat": 51.5074,
        "lng": -0.1278,
        "queries": ["pub", "restaurant", "club", "bar", "hotel", "cafe"],
    },
    "new york": {
        "lat": 40.7128,
        "lng": -74.0060,
        "queries": ["bar", "restaurant", "club", "lounge", "rooftop", "hotel"],
    },
    "los angeles": {
        "lat": 34.0522,
        "lng": -118.2437,
        "queries": ["bar", "restaurant", "club", "lounge", "hotel", "cafe"],
    },
    "tokyo": {
        "lat": 35.6762,
        "lng": 139.6503,
        "queries": ["bar", "restaurant", "izakaya", "club", "hotel", "cafe"],
    },
    "paris": {
        "lat": 48.8566,
        "lng": 2.3522,
        "queries": ["bar", "restaurant", "club", "cafe", "hotel", "bistro"],
    },
    "dubai": {
        "lat": 25.2048,
        "lng": 55.2708,
        "queries": ["bar", "restaurant", "club", "lounge", "hotel", "rooftop"],
    },
}

EMPLOYERS = [
    "Google",
    "Apple",
    "Meta",
    "Amazon",
    "Netflix",
    "Spotify",
    "Airbnb",
    "Uber",
    "Twitter",
    "TikTok",
    "Freelance",
    "Self-employed",
    "Goldman Sachs",
    "Morgan Stanley",
    "McKinsey",
    "BCG",
    "Artist",
    "Photographer",
    "Designer",
    "Architect",
]


def get_ssl_context():
    return ssl.create_default_context(cafile=certifi.where())


async def search_places(session, query: str, lat: float, lng: float) -> list:
    """Search for places near a location using Google Places API"""
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": 5000,  # 5km
        "keyword": query,
        "type": "establishment",
        "key": settings.GOOGLE_MAPS_API_KEY,
    }

    ssl_ctx = get_ssl_context()
    async with session.get(url, params=params, ssl=ssl_ctx) as response:
        data = await response.json()
        if data.get("status") == "OK":
            return data.get("results", [])[:5]  # Top 5 per query
        return []


async def get_place_photo_url(photo_reference: str) -> str:
    """Generate a photo URL from a photo reference"""
    return (
        f"https://maps.googleapis.com/maps/api/place/photo"
        f"?maxwidth=400"
        f"&photo_reference={photo_reference}"
        f"&key={settings.GOOGLE_MAPS_API_KEY}"
    )


async def seed_city(city_name: str):
    """Seed a city with venues and check-ins"""
    city_key = city_name.lower()
    if city_key not in CITIES:
        print(f"❌ Unknown city: {city_name}")
        print(f"Available cities: {', '.join(CITIES.keys())}")
        return

    city = CITIES[city_key]
    print(f"\n🌆 Seeding {city_name.title()} with venues and check-ins...")
    print(f"   Center: {city['lat']}, {city['lng']}")

    db = create_async_session()

    try:
        # Step 1: Create fake users
        print("\n👥 Creating 200 fake users...")
        user_ids = []

        for i in range(200):
            first_name = fake.first_name()
            last_name = fake.last_name()
            nickname = f"{first_name.lower()}{random.randint(1, 9999)}"

            result = await db.execute(
                text("""
                    INSERT INTO users (
                        apple_user_id, first_name, last_name, nickname,
                        employer, email, can_post, phone_visible, email_visible,
                        is_active, profile_picture
                    ) VALUES (
                        :apple_id, :first_name, :last_name, :nickname,
                        :employer, :email, true, false, false,
                        true, :profile_pic
                    ) RETURNING id
                """),
                {
                    "apple_id": f"seed_{city_key}_{fake.uuid4()}",
                    "first_name": first_name,
                    "last_name": last_name,
                    "nickname": nickname,
                    "employer": random.choice(EMPLOYERS)
                    if random.random() > 0.3
                    else None,
                    "email": fake.email() if random.random() > 0.5 else None,
                    "profile_pic": f"https://i.pravatar.cc/150?u={nickname}",
                },
            )
            user_id = result.scalar()
            user_ids.append(user_id)

            if (i + 1) % 50 == 0:
                print(f"   Created {i + 1} users...")

        await db.commit()
        print(f"✅ Created {len(user_ids)} users")

        # Step 2: Fetch real venues from Google Places
        print("\n🏢 Fetching real venues from Google Places...")
        venues = []
        seen_place_ids = set()

        async with aiohttp.ClientSession() as http_session:
            for query in city["queries"]:
                results = await search_places(
                    http_session, query, city["lat"], city["lng"]
                )
                for place in results:
                    place_id = place.get("place_id")
                    if place_id and place_id not in seen_place_ids:
                        seen_place_ids.add(place_id)

                        # Get photo URL if available
                        photo_url = None
                        photos = place.get("photos", [])
                        if photos:
                            photo_ref = photos[0].get("photo_reference")
                            if photo_ref:
                                photo_url = await get_place_photo_url(photo_ref)

                        venues.append(
                            {
                                "place_id": place_id,
                                "name": place.get("name"),
                                "lat": place["geometry"]["location"]["lat"],
                                "lng": place["geometry"]["location"]["lng"],
                                "address": place.get("vicinity", ""),
                                "photo_url": photo_url,
                                "types": place.get("types", []),
                            }
                        )

                # Limit to ~20 venues
                if len(venues) >= 20:
                    break

        print(f"✅ Found {len(venues)} venues")

        # Step 3: Create Places records
        print("\n📍 Creating place records...")
        place_db_ids = {}

        for venue in venues:
            # Check if place already exists
            result = await db.execute(
                text("SELECT id FROM places WHERE place_id = :place_id"),
                {"place_id": venue["place_id"]},
            )
            existing = result.scalar()

            if existing:
                place_db_ids[venue["place_id"]] = existing
            else:
                result = await db.execute(
                    text("""
                        INSERT INTO places (place_id, name, address, latitude, longitude, types, bounce_count, post_count)
                        VALUES (:place_id, :name, :address, :lat, :lng, :types, 0, 0)
                        RETURNING id
                    """),
                    {
                        "place_id": venue["place_id"],
                        "name": venue["name"],
                        "address": venue["address"],
                        "lat": venue["lat"],
                        "lng": venue["lng"],
                        "types": str(venue["types"]) if venue["types"] else None,
                    },
                )
                place_db_ids[venue["place_id"]] = result.scalar()

        await db.commit()
        print(f"✅ Created/found {len(place_db_ids)} place records")

        # Step 4: Create check-ins with variable amounts per venue
        print("\n✅ Creating check-ins...")
        checkin_count = 0
        now = datetime.now(timezone.utc)

        for venue in venues:
            # Random number of check-ins: 5-50 per venue
            num_checkins = random.randint(5, 50)
            checkin_users = random.sample(user_ids, min(num_checkins, len(user_ids)))

            place_db_id = place_db_ids.get(venue["place_id"])

            for user_id in checkin_users:
                # Random last_seen within last 4 hours (active check-ins)
                minutes_ago = random.randint(0, 240)
                last_seen = now - timedelta(minutes=minutes_ago)

                # Small coordinate variation (within ~50m)
                lat_offset = random.uniform(-0.0005, 0.0005)
                lng_offset = random.uniform(-0.0005, 0.0005)

                await db.execute(
                    text("""
                        INSERT INTO check_ins (
                            user_id, latitude, longitude, location_name,
                            place_id, places_fk_id, last_seen_at, is_active,
                            created_at
                        ) VALUES (
                            :user_id, :lat, :lng, :location_name,
                            :place_id, :places_fk_id, :last_seen_at, true,
                            :created_at
                        )
                    """),
                    {
                        "user_id": user_id,
                        "lat": venue["lat"] + lat_offset,
                        "lng": venue["lng"] + lng_offset,
                        "location_name": venue["name"],
                        "place_id": venue["place_id"],
                        "places_fk_id": place_db_id,
                        "last_seen_at": last_seen,
                        "created_at": last_seen
                        - timedelta(minutes=random.randint(30, 180)),
                    },
                )
                checkin_count += 1

            print(f"   {venue['name']}: {len(checkin_users)} check-ins")

        await db.commit()

        # Summary
        print("\n" + "=" * 60)
        print(f"🎉 Seeding complete for {city_name.title()}!")
        print("=" * 60)
        print(f"   Users created: {len(user_ids)}")
        print(f"   Venues found: {len(venues)}")
        print(f"   Check-ins created: {checkin_count}")
        print("=" * 60)

        # Print venue summary
        print("\n📍 Venues with check-ins:")
        for venue in venues:
            print(f"   - {venue['name']}")

    except Exception as e:
        await db.rollback()
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        await db.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/seed_checkins.py <city>")
        print("       python scripts/seed_checkins.py --list")
        print("\nExample: python scripts/seed_checkins.py miami")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--list":
        print("Available cities:")
        for city in CITIES.keys():
            print(f"  - {city}")
        sys.exit(0)

    asyncio.run(seed_city(arg))


if __name__ == "__main__":
    main()
