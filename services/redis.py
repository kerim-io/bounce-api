"""Redis service for caching and pub/sub.

Two clients: the standard text client (JSON/strings) and a binary client
(decode_responses=False) for raw image bytes. Both carry socket timeouts so a
slow Redis degrades requests instead of hanging them, plus a shared circuit
breaker so repeated failures short-circuit cache calls for a cooldown window.
"""

import logging
import time

import redis.asyncio as redis
from core.config import settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None
_redis_binary_client: redis.Redis | None = None

# --- circuit breaker (shared by cache helpers) ---
_failure_count = 0
_circuit_open_until = 0.0
FAILURE_THRESHOLD = 5
COOLDOWN_SECONDS = 30.0


def circuit_is_open() -> bool:
    return time.monotonic() < _circuit_open_until


def record_success():
    global _failure_count
    _failure_count = 0


def record_failure():
    global _failure_count, _circuit_open_until
    _failure_count += 1
    if _failure_count >= FAILURE_THRESHOLD:
        _circuit_open_until = time.monotonic() + COOLDOWN_SECONDS
        _failure_count = 0
        logger.warning(f"Redis circuit breaker opened for {COOLDOWN_SECONDS}s")


def _make_client(decode_responses: bool) -> redis.Redis:
    return redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=decode_responses,
        socket_timeout=2.0,
        socket_connect_timeout=2.0,
        retry_on_timeout=True,
        health_check_interval=30,
    )


async def get_redis() -> redis.Redis:
    """Text client (decode_responses=True) — JSON, strings, pub/sub."""
    global _redis_client
    if _redis_client is None:
        _redis_client = _make_client(decode_responses=True)
    return _redis_client


async def get_redis_binary() -> redis.Redis:
    """Binary client (decode_responses=False) — raw bytes (cached images)."""
    global _redis_binary_client
    if _redis_binary_client is None:
        _redis_binary_client = _make_client(decode_responses=False)
    return _redis_binary_client


async def close_redis():
    """Close Redis connections"""
    global _redis_client, _redis_binary_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
    if _redis_binary_client:
        await _redis_binary_client.close()
        _redis_binary_client = None


# Badge count functions
BADGE_KEY_PREFIX = "badge_count:"
BADGE_TTL = 60 * 60 * 24 * 30  # badges expire after 30 days of inactivity


async def increment_badge_count(user_id: int) -> int:
    """Increment and return the badge count for a user"""
    r = await get_redis()
    key = f"{BADGE_KEY_PREFIX}{user_id}"
    count = await r.incr(key)
    await r.expire(key, BADGE_TTL)
    return count


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
