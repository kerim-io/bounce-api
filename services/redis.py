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
