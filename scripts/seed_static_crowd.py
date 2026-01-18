"""
Seed script to create 1000 static test users split between London and Dubai.
Each user is checked into a venue with followers/following and some close friends.

Run: python scripts/seed_static_crowd.py
"""

import asyncio
import random
import uuid
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faker import Faker
from sqlalchemy import text
from db.database import create_async_session

# Profile picture placeholders (random avatars)
PROFILE_PICS = [
    "https://i.pravatar.cc/300?img=1",
    "https://i.pravatar.cc/300?img=2",
    "https://i.pravatar.cc/300?img=3",
    "https://i.pravatar.cc/300?img=4",
    "https://i.pravatar.cc/300?img=5",
    "https://i.pravatar.cc/300?img=6",
    "https://i.pravatar.cc/300?img=7",
    "https://i.pravatar.cc/300?img=8",
    "https://i.pravatar.cc/300?img=9",
    "https://i.pravatar.cc/300?img=10",
    "https://i.pravatar.cc/300?img=11",
    "https://i.pravatar.cc/300?img=12",
    "https://i.pravatar.cc/300?img=13",
    "https://i.pravatar.cc/300?img=14",
    "https://i.pravatar.cc/300?img=15",
    "https://i.pravatar.cc/300?img=16",
    "https://i.pravatar.cc/300?img=17",
    "https://i.pravatar.cc/300?img=18",
    "https://i.pravatar.cc/300?img=19",
    "https://i.pravatar.cc/300?img=20",
]

EMPLOYERS = [
    "Google", "Apple", "Meta", "Amazon", "Microsoft", "Netflix", "Spotify",
    "Goldman Sachs", "JP Morgan", "Morgan Stanley", "Blackstone", "KKR",
    "McKinsey", "BCG", "Bain", "Deloitte", "KPMG", "PwC", "EY",
    "Louis Vuitton", "Gucci", "Chanel", "Hermes", "Dior", "Prada",
    "Vogue", "GQ", "Conde Nast", "Elle", "Harper's Bazaar",
    "Art Basel", "Gagosian", "Sotheby's", "Christie's", "David Zwirner",
    "Soho House", "The Ned", "Annabel's", "Chiltern Firehouse",
    "Freelance", "Entrepreneur", "Founder", "Creative Director", "Photographer",
    "DJ", "Producer", "Model", "Influencer", "Artist", "Designer", "Architect"
]

# London venues - central/Mayfair/Soho area
LONDON_VENUES = [
    {"name": "Soho House", "address": "76 Dean St, London W1D 3SQ", "lat": 51.5138, "lon": -0.1318},
    {"name": "The Ned", "address": "27 Poultry, London EC2R 8AJ", "lat": 51.5134, "lon": -0.0903},
    {"name": "Sketch", "address": "9 Conduit St, London W1S 2XG", "lat": 51.5119, "lon": -0.1407},
    {"name": "Chiltern Firehouse", "address": "1 Chiltern St, London W1U 7PA", "lat": 51.5188, "lon": -0.1528},
    {"name": "Annabel's", "address": "46 Berkeley Square, London W1J 5AT", "lat": 51.5097, "lon": -0.1460},
    {"name": "Loulou's", "address": "5 Hertford St, London W1J 7RH", "lat": 51.5077, "lon": -0.1455},
    {"name": "The Arts Club", "address": "40 Dover St, London W1S 4NP", "lat": 51.5088, "lon": -0.1428},
    {"name": "Oswald's", "address": "25-26 Albemarle St, London W1S 4HY", "lat": 51.5092, "lon": -0.1420},
    {"name": "Harry's Bar", "address": "26 S Audley St, London W1K 2PD", "lat": 51.5096, "lon": -0.1513},
    {"name": "Scott's", "address": "20 Mount St, London W1K 2HE", "lat": 51.5100, "lon": -0.1500},
    {"name": "Sexy Fish", "address": "Berkeley Square House, London W1J 6BR", "lat": 51.5093, "lon": -0.1467},
    {"name": "Novikov", "address": "50A Berkeley St, London W1J 8HA", "lat": 51.5075, "lon": -0.1460},
    {"name": "Hakkasan", "address": "17 Bruton St, London W1J 6QB", "lat": 51.5107, "lon": -0.1435},
    {"name": "China Tang", "address": "The Dorchester, Park Ln, London W1K 1QA", "lat": 51.5070, "lon": -0.1520},
    {"name": "Gymkhana", "address": "42 Albemarle St, London W1S 4JH", "lat": 51.5093, "lon": -0.1418},
    {"name": "The Connaught Bar", "address": "Carlos Pl, London W1K 2AL", "lat": 51.5103, "lon": -0.1490},
    {"name": "Claridge's Bar", "address": "49 Brook St, London W1K 4HR", "lat": 51.5120, "lon": -0.1480},
    {"name": "The Beaumont", "address": "8 Balderton St, London W1K 6TF", "lat": 51.5130, "lon": -0.1505},
    {"name": "Cecconi's", "address": "5A Burlington Gardens, London W1S 3EP", "lat": 51.5105, "lon": -0.1397},
    {"name": "Groucho Club", "address": "45 Dean St, London W1D 4QB", "lat": 51.5133, "lon": -0.1315},
    {"name": "The Ivy", "address": "1-5 West St, London WC2H 9NQ", "lat": 51.5125, "lon": -0.1270},
    {"name": "J Sheekey", "address": "28-32 St Martin's Ct, London WC2N 4AL", "lat": 51.5108, "lon": -0.1265},
    {"name": "Nobu Berkeley", "address": "15 Berkeley St, London W1J 8DY", "lat": 51.5082, "lon": -0.1440},
    {"name": "Park Chinois", "address": "17 Berkeley St, London W1J 8EA", "lat": 51.5080, "lon": -0.1442},
    {"name": "Isabel Mayfair", "address": "26 Albemarle St, London W1S 4HY", "lat": 51.5090, "lon": -0.1422},
]

# Dubai venues - DIFC/Downtown/Marina
DUBAI_VENUES = [
    {"name": "Zuma Dubai", "address": "Gate Village 06, DIFC, Dubai", "lat": 25.2117, "lon": 55.2789},
    {"name": "Coya Dubai", "address": "Four Seasons Resort, Jumeirah Beach Rd", "lat": 25.2095, "lon": 55.2385},
    {"name": "La Petite Maison", "address": "Gate Village 08, DIFC, Dubai", "lat": 25.2120, "lon": 55.2795},
    {"name": "Cipriani", "address": "DIFC, Dubai", "lat": 25.2110, "lon": 55.2780},
    {"name": "Billionaire Mansion", "address": "Taj Hotel, Business Bay, Dubai", "lat": 25.1865, "lon": 55.2625},
    {"name": "Cavalli Club", "address": "Fairmont Hotel, Sheikh Zayed Rd", "lat": 25.2230, "lon": 55.2820},
    {"name": "White Dubai", "address": "Meydan Racecourse, Dubai", "lat": 25.1650, "lon": 55.3020},
    {"name": "Base Dubai", "address": "Dubai Design District", "lat": 25.1862, "lon": 55.2980},
    {"name": "Nammos Dubai", "address": "Four Seasons Resort, Jumeirah Beach", "lat": 25.2098, "lon": 55.2380},
    {"name": "MNKY HSE", "address": "Media One Hotel, Dubai Marina", "lat": 25.0775, "lon": 55.1340},
    {"name": "Amazonico", "address": "Gate Avenue, DIFC", "lat": 25.2105, "lon": 55.2785},
    {"name": "Nusr-Et Steakhouse", "address": "Four Seasons Resort, Jumeirah Beach", "lat": 25.2090, "lon": 55.2378},
    {"name": "Nobu Dubai", "address": "Atlantis The Palm, Dubai", "lat": 25.1305, "lon": 55.1175},
    {"name": "Hakkasan Dubai", "address": "Atlantis The Palm, Dubai", "lat": 25.1307, "lon": 55.1178},
    {"name": "Tresind Studio", "address": "DIFC, Dubai", "lat": 25.2115, "lon": 55.2792},
    {"name": "La Cantine du Faubourg", "address": "Emirates Towers, Dubai", "lat": 25.2175, "lon": 55.2820},
    {"name": "Catch Dubai", "address": "Fairmont Hotel, Sheikh Zayed Rd", "lat": 25.2232, "lon": 55.2825},
    {"name": "Iris Dubai", "address": "Oberoi Hotel, Business Bay", "lat": 25.1855, "lon": 55.2615},
    {"name": "Soho Garden", "address": "Meydan Hotel, Dubai", "lat": 25.1655, "lon": 55.3025},
    {"name": "Atmosphere Burj Khalifa", "address": "Burj Khalifa, Downtown Dubai", "lat": 25.1972, "lon": 55.2744},
    {"name": "At.mosphere Lounge", "address": "Burj Khalifa Level 122, Dubai", "lat": 25.1970, "lon": 55.2742},
    {"name": "Sass Cafe", "address": "DIFC, Dubai", "lat": 25.2118, "lon": 55.2790},
    {"name": "Roberto's", "address": "DIFC, Gate Village", "lat": 25.2112, "lon": 55.2787},
    {"name": "Twiggy by La Cantine", "address": "Park Hyatt, Dubai Creek", "lat": 25.2405, "lon": 55.3345},
    {"name": "Penthouse Dubai", "address": "FIVE Palm Jumeirah, Dubai", "lat": 25.1125, "lon": 55.1385},
]


async def seed_static_crowd():
    """Main seed function"""
    fake = Faker()
    db = create_async_session()

    print("Starting static crowd seeding...")

    try:
        # 1. Clean up existing test data
        print("Cleaning up existing test data...")
        await db.execute(text("""
            DELETE FROM check_ins WHERE user_id IN (
                SELECT id FROM users WHERE apple_user_id LIKE 'test_user_%'
            )
        """))
        await db.execute(text("""
            DELETE FROM follows WHERE follower_id IN (
                SELECT id FROM users WHERE apple_user_id LIKE 'test_user_%'
            ) OR following_id IN (
                SELECT id FROM users WHERE apple_user_id LIKE 'test_user_%'
            )
        """))
        await db.execute(text("DELETE FROM users WHERE apple_user_id LIKE 'test_user_%'"))
        await db.execute(text("""
            DELETE FROM google_pics WHERE place_id IN (
                SELECT id FROM places WHERE place_id LIKE 'test_place_%'
            )
        """))
        await db.execute(text("DELETE FROM places WHERE place_id LIKE 'test_place_%'"))
        await db.commit()
        print("Cleanup complete.")

        # 2. Create venues
        print("Creating venues...")
        london_place_ids = []
        dubai_place_ids = []

        for i, venue in enumerate(LONDON_VENUES):
            place_id = f"test_place_london_{i}"
            await db.execute(text("""
                INSERT INTO places (place_id, name, address, latitude, longitude, bounce_count)
                VALUES (:place_id, :name, :address, :lat, :lon, 0)
                ON CONFLICT (place_id) DO NOTHING
            """), {"place_id": place_id, "name": venue["name"], "address": venue["address"],
                   "lat": venue["lat"], "lon": venue["lon"]})
            london_place_ids.append({"place_id": place_id, **venue})

        for i, venue in enumerate(DUBAI_VENUES):
            place_id = f"test_place_dubai_{i}"
            await db.execute(text("""
                INSERT INTO places (place_id, name, address, latitude, longitude, bounce_count)
                VALUES (:place_id, :name, :address, :lat, :lon, 0)
                ON CONFLICT (place_id) DO NOTHING
            """), {"place_id": place_id, "name": venue["name"], "address": venue["address"],
                   "lat": venue["lat"], "lon": venue["lon"]})
            dubai_place_ids.append({"place_id": place_id, **venue})

        await db.commit()
        print(f"Created {len(london_place_ids)} London venues, {len(dubai_place_ids)} Dubai venues.")

        # Get place FKs
        result = await db.execute(text("SELECT id, place_id FROM places WHERE place_id LIKE 'test_place_%'"))
        place_fks = {row.place_id: row.id for row in result.fetchall()}

        # 2b. Add venue photos (so pins show images not counts)
        print("Adding venue photos...")
        # Placeholder venue photos - high quality venue/restaurant images
        VENUE_PHOTOS = [
            "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=400",  # restaurant interior
            "https://images.unsplash.com/photo-1552566626-52f8b828add9?w=400",  # restaurant
            "https://images.unsplash.com/photo-1514933651103-005eec06c04b?w=400",  # bar
            "https://images.unsplash.com/photo-1559329007-40df8a9345d8?w=400",  # restaurant night
            "https://images.unsplash.com/photo-1466978913421-dad2ebd01d17?w=400",  # cafe
            "https://images.unsplash.com/photo-1525610553991-2bede1a236e2?w=400",  # lounge
            "https://images.unsplash.com/photo-1554679665-f5537f187268?w=400",  # cocktail bar
            "https://images.unsplash.com/photo-1537047902294-62a40c20a6ae?w=400",  # fine dining
            "https://images.unsplash.com/photo-1550966871-3ed3cdb5ed0c?w=400",  # restaurant terrace
            "https://images.unsplash.com/photo-1560624052-449f5ddf0c31?w=400",  # club
        ]

        for place_id_str, place_fk_id in place_fks.items():
            photo_url = random.choice(VENUE_PHOTOS)
            await db.execute(text("""
                INSERT INTO google_pics (place_id, photo_reference, photo_url, width, height)
                VALUES (:place_id, :ref, :url, 400, 400)
                ON CONFLICT DO NOTHING
            """), {
                "place_id": place_fk_id,
                "ref": f"test_photo_{place_id_str}",
                "url": photo_url
            })
        await db.commit()
        print(f"Added photos for {len(place_fks)} venues.")

        # 3. Create users
        print("Creating 1000 users...")
        user_ids = []

        for i in range(1000):
            city = "london" if i < 500 else "dubai"
            venues = london_place_ids if city == "london" else dubai_place_ids
            venue = random.choice(venues)

            apple_user_id = f"test_user_{uuid.uuid4().hex[:16]}"
            first_name = fake.first_name()
            last_name = fake.last_name()
            nickname = f"{first_name.lower()}_{random.randint(100, 999)}"
            employer = random.choice(EMPLOYERS)
            profile_pic = random.choice(PROFILE_PICS)

            # Add small random offset to coordinates (within ~50m)
            lat_offset = random.uniform(-0.0005, 0.0005)
            lon_offset = random.uniform(-0.0005, 0.0005)

            await db.execute(text("""
                INSERT INTO users (apple_user_id, first_name, last_name, nickname, employer,
                                   profile_picture, can_post, is_active, phone_visible, email_visible)
                VALUES (:apple_user_id, :first_name, :last_name, :nickname, :employer,
                        :profile_picture, true, true, false, false)
                RETURNING id
            """), {
                "apple_user_id": apple_user_id,
                "first_name": first_name,
                "last_name": last_name,
                "nickname": nickname,
                "employer": employer,
                "profile_picture": profile_pic
            })

            # Get the user ID
            result = await db.execute(text("SELECT id FROM users WHERE apple_user_id = :aid"),
                                       {"aid": apple_user_id})
            user_id = result.scalar()
            user_ids.append({"id": user_id, "city": city, "venue": venue})

            # Create check-in
            places_fk_id = place_fks.get(venue["place_id"])
            await db.execute(text("""
                INSERT INTO check_ins (user_id, latitude, longitude, location_name, place_id, places_fk_id, is_active)
                VALUES (:user_id, :lat, :lon, :name, :place_id, :places_fk_id, true)
            """), {
                "user_id": user_id,
                "lat": venue["lat"] + lat_offset,
                "lon": venue["lon"] + lon_offset,
                "name": venue["name"],
                "place_id": venue["place_id"],
                "places_fk_id": places_fk_id
            })

            if (i + 1) % 100 == 0:
                await db.commit()
                print(f"  Created {i + 1} users...")

        await db.commit()
        print("All 1000 users created with check-ins.")

        # 4. Create follow relationships
        print("Creating follow relationships...")
        follow_count = 0
        all_user_ids = [u["id"] for u in user_ids]

        for user in user_ids:
            # Each user follows 5-20 random other users
            num_follows = random.randint(5, 20)
            follows = random.sample([uid for uid in all_user_ids if uid != user["id"]],
                                    min(num_follows, len(all_user_ids) - 1))

            for follow_id in follows:
                await db.execute(text("""
                    INSERT INTO follows (follower_id, following_id, is_close_friend, close_friend_status)
                    VALUES (:follower, :following, false, 'none')
                    ON CONFLICT DO NOTHING
                """), {"follower": user["id"], "following": follow_id})
                follow_count += 1

            if follow_count % 1000 == 0:
                await db.commit()
                print(f"  Created {follow_count} follow relationships...")

        await db.commit()
        print(f"Created {follow_count} follow relationships.")

        # 5. Set close friend status for mutual follows
        print("Setting close friend statuses...")
        result = await db.execute(text("""
            SELECT f1.id as f1_id, f1.follower_id, f1.following_id, f2.id as f2_id
            FROM follows f1
            JOIN follows f2 ON f1.follower_id = f2.following_id AND f1.following_id = f2.follower_id
            WHERE f1.follower_id IN (SELECT id FROM users WHERE apple_user_id LIKE 'test_user_%')
            AND f1.id < f2.id
        """))
        mutual_follows = result.fetchall()
        print(f"Found {len(mutual_follows)} mutual follow pairs.")

        # Set ~10% as close friends
        close_friend_pairs = random.sample(list(mutual_follows), min(len(mutual_follows) // 10, len(mutual_follows)))

        for pair in close_friend_pairs:
            await db.execute(text("""
                UPDATE follows
                SET is_close_friend = true, close_friend_status = 'accepted'
                WHERE id IN (:f1_id, :f2_id)
            """), {"f1_id": pair.f1_id, "f2_id": pair.f2_id})

        await db.commit()
        print(f"Set {len(close_friend_pairs)} close friend pairs ({len(close_friend_pairs) * 2} relationships).")

        # Final stats
        print("\n=== Seeding Complete ===")
        result = await db.execute(text("SELECT COUNT(*) FROM users WHERE apple_user_id LIKE 'test_user_%'"))
        print(f"Total test users: {result.scalar()}")

        result = await db.execute(text("""
            SELECT COUNT(*) FROM check_ins WHERE user_id IN
            (SELECT id FROM users WHERE apple_user_id LIKE 'test_user_%') AND is_active = true
        """))
        print(f"Active check-ins: {result.scalar()}")

        result = await db.execute(text("""
            SELECT COUNT(*) FROM follows WHERE follower_id IN
            (SELECT id FROM users WHERE apple_user_id LIKE 'test_user_%')
        """))
        print(f"Follow relationships: {result.scalar()}")

        result = await db.execute(text("""
            SELECT COUNT(*) FROM follows WHERE close_friend_status = 'accepted' AND follower_id IN
            (SELECT id FROM users WHERE apple_user_id LIKE 'test_user_%')
        """))
        print(f"Close friend relationships: {result.scalar()}")

    except Exception as e:
        print(f"Error: {e}")
        await db.rollback()
        raise
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(seed_static_crowd())
