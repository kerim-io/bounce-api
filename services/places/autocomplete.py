"""
Global Places Autocomplete and Nearby Search Service

Provides location-independent autocomplete against cached places using Redis,
with prefix matching, popularity scoring, and distance re-ranking.

Also provides global geo-index for nearby searches, replacing wasteful
per-location caching with a single global index.

Redis Data Structures:
- places:autocomplete:index (sorted set) - prefix search via ZRANGEBYLEX
- places:geo (geo set) - radius search via GEORADIUS
- places:meta:{place_id} (hash) - shared metadata for both search types
"""

import json
import logging
import math
import time
import unicodedata
from typing import List, Optional, Tuple

from services.redis import get_redis

logger = logging.getLogger(__name__)

# Redis key constants
AUTOCOMPLETE_INDEX = "places:autocomplete:index"
GEO_INDEX = "places:geo"
META_PREFIX = "places:meta:"
META_TTL = 30 * 24 * 3600  # 30 days


def normalize_name(name: str) -> str:
    """
    Normalize place name for consistent prefix matching.

    - Lowercase
    - Remove diacritics (Schümann's -> schumann's)
    - Keep only alphanumeric and spaces
    - Collapse multiple spaces
    """
    # Lowercase
    name = name.lower()
    # Remove diacritics (NFD decomposition + filter combining chars)
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))
    # Keep only alphanumeric and spaces
    name = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in name)
    # Collapse multiple spaces
    name = ' '.join(name.split())
    return name.strip()


async def index_place(
    place_id: str,
    name: str,
    address: str,
    lat: float,
    lng: float,
    types: Optional[List[str]] = None,
    bounce_count: int = 0,
    photo_url: Optional[str] = None
) -> bool:
    """
    Add or update a place in all global indexes.

    This function atomically updates:
    1. places:autocomplete:index (sorted set for prefix search)
    2. places:geo (geo set for radius search)
    3. places:meta:{place_id} (hash with full metadata)

    Returns True on success, False on failure.
    """
    try:
        redis = await get_redis()

        # Normalize name for prefix index
        normalized = normalize_name(name)
        if not normalized:
            logger.warning(f"Empty normalized name for place {place_id}, skipping index")
            return False

        # Build index entries starting from each word so "The Monocle Cafe"
        # is findable by "monocle" and "cafe", not just "the monocle"
        words = normalized.split()
        index_entries = {}
        for i in range(len(words)):
            suffix = " ".join(words[i:])
            index_entries[f"{suffix}:{place_id}"] = 0

        # Use pipeline for atomic operations
        pipe = redis.pipeline()

        # 1. Add all suffix entries to prefix index (score=0 for lexicographic ordering)
        pipe.zadd(AUTOCOMPLETE_INDEX, index_entries)

        # 2. Add to geo index (GEOADD uses lng, lat order)
        pipe.geoadd(GEO_INDEX, (lng, lat, place_id))

        # 3. Store/update metadata
        meta_key = f"{META_PREFIX}{place_id}"
        metadata = {
            "name": name,
            "address": address or "",
            "lat": str(lat),
            "lng": str(lng),
            "bounce_count": str(bounce_count),
            "types": json.dumps(types or []),
            "indexed_at": str(int(time.time()))
        }
        if photo_url:
            metadata["photo_url"] = photo_url

        pipe.hset(meta_key, mapping=metadata)
        pipe.expire(meta_key, META_TTL)

        await pipe.execute()
        logger.debug(f"Indexed place {place_id}: {name}")
        return True

    except Exception as e:
        logger.error(f"Failed to index place {place_id}: {e}")
        return False


async def remove_place_from_index(place_id: str, normalized_name: str) -> bool:
    """
    Remove a place from all indexes (used when updating name).
    """
    try:
        redis = await get_redis()

        # Remove all suffix entries for this place
        words = normalized_name.split()
        entries_to_remove = []
        for i in range(len(words)):
            suffix = " ".join(words[i:])
            entries_to_remove.append(f"{suffix}:{place_id}")

        pipe = redis.pipeline()
        if entries_to_remove:
            pipe.zrem(AUTOCOMPLETE_INDEX, *entries_to_remove)
        pipe.zrem(GEO_INDEX, place_id)
        pipe.delete(f"{META_PREFIX}{place_id}")
        await pipe.execute()

        return True
    except Exception as e:
        logger.error(f"Failed to remove place {place_id} from index: {e}")
        return False


async def increment_bounce_count(place_id: str) -> int:
    """
    Atomically increment bounce count for a place.
    Returns the new count, or -1 on failure.
    """
    try:
        redis = await get_redis()
        meta_key = f"{META_PREFIX}{place_id}"

        # Check if the place exists in cache
        if not await redis.exists(meta_key):
            return -1

        # Atomic increment + refresh TTL
        pipe = redis.pipeline()
        pipe.hincrby(meta_key, "bounce_count", 1)
        pipe.expire(meta_key, META_TTL)
        results = await pipe.execute()

        return results[0]  # New bounce count

    except Exception as e:
        logger.error(f"Failed to increment bounce count for {place_id}: {e}")
        return -1


async def global_autocomplete_search(
    query: str,
    user_lat: Optional[float] = None,
    user_lng: Optional[float] = None,
    limit: int = 10
) -> Tuple[List[dict], bool]:
    """
    Search global cache for places matching query prefix.

    Uses ZRANGEBYLEX for O(log N + M) prefix matching.
    Results are scored by distance (if location provided) + popularity.

    Returns:
        Tuple of (list of place dicts with PlacePrediction-compatible fields, cache_hit bool)
    """
    try:
        redis = await get_redis()

        # Normalize query for prefix matching
        normalized_query = normalize_name(query)
        if not normalized_query:
            return [], False

        # Prefix search: get entries starting with query
        # "[query" = inclusive lower bound, "[query\xff" = exclusive upper bound
        min_lex = f"[{normalized_query}"
        max_lex = f"[{normalized_query}\xff"

        # Fetch more than limit to allow for scoring/filtering
        raw_entries = await redis.zrangebylex(
            AUTOCOMPLETE_INDEX,
            min_lex,
            max_lex,
            start=0,
            num=limit * 5  # Fetch extra for filtering
        )

        if not raw_entries:
            return [], False

        # Extract place_ids from entries (format: "normalized_name:place_id")
        place_ids = []
        for entry in raw_entries:
            parts = entry.rsplit(":", 1)
            if len(parts) == 2:
                place_ids.append(parts[1])

        if not place_ids:
            return [], False

        # Pipeline fetch all metadata
        pipe = redis.pipeline()
        for pid in place_ids:
            pipe.hgetall(f"{META_PREFIX}{pid}")
        metadata_results = await pipe.execute()

        # Build results with scores
        results = []
        for i, meta in enumerate(metadata_results):
            if not meta:
                continue

            place_id = place_ids[i]
            lat = float(meta.get("lat", 0))
            lng = float(meta.get("lng", 0))
            bounce_count = int(meta.get("bounce_count", 0))

            # Calculate distance if user location provided
            distance_meters = None
            if user_lat is not None and user_lng is not None:
                distance_meters = haversine_distance_meters(user_lat, user_lng, lat, lng)

            # Calculate combined score
            score = calculate_score(bounce_count, distance_meters)

            # Parse types
            types_str = meta.get("types", "[]")
            try:
                types = json.loads(types_str)
            except:
                types = []

            results.append({
                "place_id": place_id,
                "name": meta.get("name", ""),
                "address": meta.get("address", ""),
                "full_description": f"{meta.get('name', '')} - {meta.get('address', '')}" if meta.get("address") else meta.get("name", ""),
                "latitude": lat,
                "longitude": lng,
                "distance_meters": distance_meters,
                "bounce_count": bounce_count,
                "photo_url": meta.get("photo_url"),
                "types": types,
                "_score": score  # Internal, for sorting
            })

        # Sort by score (higher = better)
        results.sort(key=lambda x: x["_score"], reverse=True)

        # Remove internal score field and limit results
        for r in results:
            del r["_score"]

        return results[:limit], True

    except Exception as e:
        logger.error(f"Global autocomplete search failed: {e}")
        return [], False



def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Calculate distance between two points in meters using Haversine formula."""
    R = 6371000  # Earth's radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return int(R * c)


def calculate_score(bounce_count: int, distance_meters: Optional[int]) -> float:
    """
    Calculate ranking score combining popularity and distance.
    Higher score = better match.

    - Distance score: 100 (< 1km) -> 5 (> 1000km)
    - Popularity score: log1p(bounce_count) * 10
    - Combined: (distance * 0.6) + (popularity * 0.4)
    - No location: popularity only (doubled weight)
    """
    # Popularity component (log scale to prevent dominance by super-popular venues)
    popularity_score = math.log1p(bounce_count) * 10  # 0-50 range typical

    # Distance component
    if distance_meters is None:
        # No location provided - popularity only
        return popularity_score * 2

    if distance_meters < 1000:  # < 1km
        distance_score = 100
    elif distance_meters < 5000:  # < 5km
        distance_score = 80
    elif distance_meters < 10000:  # < 10km
        distance_score = 60
    elif distance_meters < 50000:  # < 50km
        distance_score = 40
    elif distance_meters < 100000:  # < 100km
        distance_score = 20
    elif distance_meters < 1000000:  # < 1000km
        distance_score = 10
    else:
        distance_score = 5  # Far away still gets some points

    # Combined score (distance weighted higher for local relevance)
    return (distance_score * 0.6) + (popularity_score * 0.4)


async def get_indexed_place_count() -> int:
    """Get the number of places currently in the global index."""
    try:
        redis = await get_redis()
        return await redis.zcard(AUTOCOMPLETE_INDEX)
    except Exception:
        return -1


async def sync_db_place_to_redis(
    place_id: str,
    name: str,
    address: Optional[str],
    lat: float,
    lng: float,
    types: Optional[str],  # JSON string from DB
    bounce_count: int
) -> bool:
    """
    Sync a single database Place record to Redis.
    Used by the sync script to populate the index.
    """
    types_list = []
    if types:
        try:
            types_list = json.loads(types)
        except:
            pass

    return await index_place(
        place_id=place_id,
        name=name,
        address=address or "",
        lat=lat,
        lng=lng,
        types=types_list,
        bounce_count=bounce_count
    )
