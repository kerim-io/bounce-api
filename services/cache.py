"""Redis caching service for high-traffic endpoints"""

import json
from typing import Any, Optional
from services.redis import get_redis

# 7 days in seconds
DEFAULT_TTL = 604800


async def cache_get(key: str, reset_ttl: bool = True) -> Optional[Any]:
    """Get value from cache, returns None if not found or Redis unavailable.
    Resets TTL to 7 days on access by default."""
    try:
        redis = await get_redis()
        value = await redis.get(key)
        if value:
            if reset_ttl:
                await redis.expire(key, DEFAULT_TTL)
            return json.loads(value)
        return None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    """Set value in cache with TTL in seconds (default 7 days)"""
    try:
        redis = await get_redis()
        await redis.setex(key, ttl, json.dumps(value))
    except Exception:
        pass  # Fail silently - caching is optional


async def cache_delete(key: str) -> None:
    """Delete a single cache key"""
    try:
        redis = await get_redis()
        await redis.delete(key)
    except Exception:
        pass


async def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching pattern (e.g., 'user_stats:*')"""
    try:
        redis = await get_redis()
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        pass
