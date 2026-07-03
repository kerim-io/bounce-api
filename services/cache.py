"""Redis JSON cache: real TTLs, stale-while-revalidate, single-flight.

Rules learned the hard way:
- Reads NEVER silently extend TTLs (the old reset-to-7-days default is gone).
- Failures are logged (rate-limited) and trip the shared circuit breaker,
  so a Redis outage is visible instead of silently becoming a Google bill.
- cache_get_swr/cache_set_swr wrap values in {"v", "e"} envelopes: callers
  can serve a stale value instantly and refresh in the background.
- single_flight(key) hands out a per-key asyncio.Lock so concurrent misses
  don't stampede the upstream.
"""

import asyncio
import json
import logging
import time
from typing import Any, Optional

from services.redis import (
    circuit_is_open,
    get_redis,
    record_failure,
    record_success,
)

logger = logging.getLogger(__name__)

DEFAULT_TTL = 86400  # 1 day

_LOG_INTERVAL = 60.0
_last_error_log = 0.0


def _log_error(op: str, e: Exception):
    global _last_error_log
    now = time.monotonic()
    if now - _last_error_log > _LOG_INTERVAL:
        _last_error_log = now
        logger.warning(f"Redis cache {op} failed: {e}")


async def cache_get(key: str, reset_ttl: bool = False) -> Optional[Any]:
    """Get JSON value from cache. Returns None if missing or Redis unavailable.
    reset_ttl is opt-in ONLY (sliding expiry to DEFAULT_TTL) — never default."""
    if circuit_is_open():
        return None
    try:
        redis = await get_redis()
        value = await redis.get(key)
        record_success()
        if value:
            if reset_ttl:
                await redis.expire(key, DEFAULT_TTL)
            return json.loads(value)
        return None
    except Exception as e:
        record_failure()
        _log_error("get", e)
        return None


async def cache_set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    """Set value in cache with TTL in seconds (default 1 day)."""
    if circuit_is_open():
        return
    try:
        redis = await get_redis()
        await redis.setex(key, ttl, json.dumps(value))
        record_success()
    except Exception as e:
        record_failure()
        _log_error("set", e)


async def cache_delete(key: str) -> None:
    """Delete a single cache key"""
    if circuit_is_open():
        return
    try:
        redis = await get_redis()
        await redis.delete(key)
        record_success()
    except Exception as e:
        record_failure()
        _log_error("delete", e)


async def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching pattern (e.g., 'user_stats:*')"""
    if circuit_is_open():
        return
    try:
        redis = await get_redis()
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
        record_success()
    except Exception as e:
        record_failure()
        _log_error("delete_pattern", e)


# ---------- stale-while-revalidate ----------

async def cache_get_swr(key: str) -> tuple[Optional[Any], bool]:
    """Returns (value, is_stale). Value None = miss. is_stale True means the
    caller should serve it now but refresh in the background."""
    envelope = await cache_get(key)
    if not isinstance(envelope, dict) or "v" not in envelope:
        return None, False
    return envelope["v"], time.time() > envelope.get("e", 0)


async def cache_set_swr(key: str, value: Any, ttl: int, grace: int = 3600) -> None:
    """Store with a freshness horizon of `ttl` seconds; the entry survives an
    extra `grace` seconds during which it is served as stale."""
    await cache_set(key, {"v": value, "e": time.time() + ttl}, ttl=ttl + grace)


# ---------- single-flight ----------

_flight_locks: dict[str, asyncio.Lock] = {}
_flight_guard = asyncio.Lock()


async def single_flight(key: str) -> asyncio.Lock:
    """Per-key lock so concurrent cache misses fetch upstream once."""
    async with _flight_guard:
        if len(_flight_locks) > 2048:
            # Bound memory; losing locks only means a rare duplicate fetch
            _flight_locks.clear()
        lock = _flight_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _flight_locks[key] = lock
        return lock
