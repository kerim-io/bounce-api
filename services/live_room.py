"""Shared primitives for live-room WebSockets (venue feeds, bounce rooms).

Viewer presence is a Redis ZSET per room (member = connection id, score =
expiry timestamp) so counts stay correct across instances and survive dead
connections. Reactions are ephemeral hearts — rate-limited per connection,
broadcast to the room, never stored.
"""

import asyncio
import time

from services.redis import get_redis

VIEWER_TTL_SECONDS = 60
REACTION_MAX_PER_WINDOW = 30
REACTION_WINDOW_SECONDS = 5.0
REACTION_MAX_PER_FRAME = 20


async def register_viewer(key: str, conn_id: str) -> int:
    """Add a viewer connection to the room's ZSET. Returns the live count."""
    redis = await get_redis()
    now = time.time()
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, "-inf", now)
    pipe.zadd(key, {conn_id: now + VIEWER_TTL_SECONDS})
    pipe.expire(key, VIEWER_TTL_SECONDS * 2)
    pipe.zcard(key)
    results = await pipe.execute()
    return int(results[3])


async def refresh_viewer(key: str, conn_id: str):
    redis = await get_redis()
    now = time.time()
    await redis.zadd(key, {conn_id: now + VIEWER_TTL_SECONDS})


async def unregister_viewer(key: str, conn_id: str) -> int:
    redis = await get_redis()
    pipe = redis.pipeline()
    pipe.zrem(key, conn_id)
    pipe.zremrangebyscore(key, "-inf", time.time())
    pipe.zcard(key)
    results = await pipe.execute()
    return int(results[2])


async def viewer_refresh_loop(key: str, conn_id: str):
    """Keep a connection's viewer entry alive. Clients may only ping at the
    WS protocol level (never reaching receive_text), so refresh server-side."""
    while True:
        await asyncio.sleep(VIEWER_TTL_SECONDS // 2)
        try:
            await refresh_viewer(key, conn_id)
        except Exception:
            pass


class ReactionThrottle:
    """Per-connection sliding-window limit on ephemeral heart reactions."""

    def __init__(self):
        self.window_start = time.monotonic()
        self.count = 0

    def allow(self, requested) -> int:
        """Return how many of the requested hearts may broadcast (0 = drop)."""
        now = time.monotonic()
        if now - self.window_start >= REACTION_WINDOW_SECONDS:
            self.window_start = now
            self.count = 0
        try:
            requested = int(requested)
        except (TypeError, ValueError):
            return 0
        requested = max(1, min(requested, REACTION_MAX_PER_FRAME))
        allowed = min(requested, REACTION_MAX_PER_WINDOW - self.count)
        if allowed <= 0:
            return 0
        self.count += allowed
        return allowed
