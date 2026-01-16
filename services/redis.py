"""Redis service for caching and pub/sub"""

import redis.asyncio as redis
from core.config import settings

_redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Get Redis client instance (lazy initialization)"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )
    return _redis_client


async def close_redis():
    """Close Redis connection"""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None


# Badge count functions
BADGE_KEY_PREFIX = "badge_count:"


async def increment_badge_count(user_id: int) -> int:
    """Increment and return the badge count for a user"""
    r = await get_redis()
    key = f"{BADGE_KEY_PREFIX}{user_id}"
    return await r.incr(key)


async def get_badge_count(user_id: int) -> int:
    """Get current badge count for a user"""
    r = await get_redis()
    key = f"{BADGE_KEY_PREFIX}{user_id}"
    count = await r.get(key)
    return int(count) if count else 0


async def reset_badge_count(user_id: int) -> None:
    """Reset badge count to 0 for a user"""
    r = await get_redis()
    key = f"{BADGE_KEY_PREFIX}{user_id}"
    await r.delete(key)
