from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import List, Dict
import asyncio
import json
import logging

from services.redis import get_redis

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)

REDIS_CHANNEL_BROADCAST = "ws:broadcast"
REDIS_CHANNEL_USER = "ws:user:{user_id}"
REDIS_CHANNEL_BOUNCE = "ws:bounce:{bounce_id}"
REDIS_CHANNEL_VENUE_FEED = "ws:venue_feed:{place_id}"


class ConnectionManager:
    """WebSocket manager with Redis pub/sub for multi-instance support"""

    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.bounce_connections: Dict[int, List[WebSocket]] = {}  # bounce_id -> guest websockets
        self.venue_feed_connections: Dict[str, List[WebSocket]] = {}  # place_id -> websockets
        self._subscriber_task: asyncio.Task | None = None
        self._pubsub = None  # Redis pubsub instance for dynamic subscriptions

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        is_new_user = user_id not in self.active_connections
        if is_new_user:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

        # Subscribe to user-specific channel if this is their first connection
        if is_new_user and self._pubsub is not None:
            try:
                channel = REDIS_CHANNEL_USER.format(user_id=user_id)
                await self._pubsub.subscribe(channel)
                logger.debug(f"Subscribed to Redis channel for user {user_id}")
            except Exception as e:
                logger.warning(f"Failed to subscribe to user channel: {e}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                # Unsubscribe from user channel when they have no more connections
                if self._pubsub is not None:
                    asyncio.create_task(self._unsubscribe_user(user_id))

    async def _unsubscribe_user(self, user_id: int):
        """Unsubscribe from a user's Redis channel"""
        try:
            channel = REDIS_CHANNEL_USER.format(user_id=user_id)
            await self._pubsub.unsubscribe(channel)
            logger.debug(f"Unsubscribed from Redis channel for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to unsubscribe from user channel: {e}")

    async def _send_local(self, message: dict, user_id: int | None = None):
        """Send to local connections only"""
        dead_connections = []

        if user_id is not None:
            connections_to_send = [(user_id, self.active_connections.get(user_id, []))]
        else:
            connections_to_send = list(self.active_connections.items())

        for uid, connections in connections_to_send:
            for connection in connections:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead_connections.append((uid, connection))

        for uid, connection in dead_connections:
            self.disconnect(connection, uid)

    async def broadcast(self, message: dict):
        """Broadcast to all connected clients across all instances via Redis"""
        try:
            redis = await get_redis()
            await redis.publish(REDIS_CHANNEL_BROADCAST, json.dumps(message))
        except Exception as e:
            logger.warning(f"Redis broadcast failed, falling back to local: {e}")
            await self._send_local(message)

    async def send_to_user(self, user_id: int, message: dict):
        """Send to specific user across all instances via Redis"""
        try:
            redis = await get_redis()
            channel = REDIS_CHANNEL_USER.format(user_id=user_id)
            await redis.publish(channel, json.dumps(message))
            return True
        except Exception as e:
            logger.warning(f"Redis send_to_user failed, falling back to local: {e}")
            await self._send_local(message, user_id)
            return user_id in self.active_connections

    async def connect_guest(self, websocket: WebSocket, bounce_id: int):
        """Accept and track a guest WebSocket for a bounce share page"""
        await websocket.accept()
        is_new_bounce = bounce_id not in self.bounce_connections
        if is_new_bounce:
            self.bounce_connections[bounce_id] = []
        self.bounce_connections[bounce_id].append(websocket)

        # Subscribe to bounce channel if new
        if is_new_bounce and self._pubsub is not None:
            try:
                channel = REDIS_CHANNEL_BOUNCE.format(bounce_id=bounce_id)
                await self._pubsub.subscribe(channel)
                logger.debug(f"Subscribed to Redis channel for bounce {bounce_id}")
            except Exception as e:
                logger.warning(f"Failed to subscribe to bounce channel: {e}")

    def disconnect_guest(self, websocket: WebSocket, bounce_id: int):
        """Remove a guest WebSocket from bounce tracking"""
        if bounce_id in self.bounce_connections:
            if websocket in self.bounce_connections[bounce_id]:
                self.bounce_connections[bounce_id].remove(websocket)
            if not self.bounce_connections[bounce_id]:
                del self.bounce_connections[bounce_id]
                if self._pubsub is not None:
                    asyncio.create_task(self._unsubscribe_bounce(bounce_id))

    async def _unsubscribe_bounce(self, bounce_id: int):
        """Unsubscribe from a bounce's Redis channel"""
        try:
            channel = REDIS_CHANNEL_BOUNCE.format(bounce_id=bounce_id)
            await self._pubsub.unsubscribe(channel)
            logger.debug(f"Unsubscribed from Redis channel for bounce {bounce_id}")
        except Exception as e:
            logger.warning(f"Failed to unsubscribe from bounce channel: {e}")

    async def _send_to_bounce_local(self, bounce_id: int, message: dict):
        """Send to all local guest connections for a bounce"""
        dead_connections = []
        for ws in self.bounce_connections.get(bounce_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.append(ws)
        for ws in dead_connections:
            self.disconnect_guest(ws, bounce_id)

    async def send_to_bounce(self, bounce_id: int, message: dict):
        """Send to all guest WebSockets for a bounce across all instances via Redis"""
        try:
            redis = await get_redis()
            channel = REDIS_CHANNEL_BOUNCE.format(bounce_id=bounce_id)
            await redis.publish(channel, json.dumps(message))
        except Exception as e:
            logger.warning(f"Redis send_to_bounce failed, falling back to local: {e}")
            await self._send_to_bounce_local(bounce_id, message)

    # ---- venue feed ----

    async def connect_venue_feed(self, websocket: WebSocket, place_id: str):
        """Accept and track a WebSocket for a venue feed"""
        await websocket.accept()
        is_new = place_id not in self.venue_feed_connections
        if is_new:
            self.venue_feed_connections[place_id] = []
        self.venue_feed_connections[place_id].append(websocket)

        if is_new and self._pubsub is not None:
            try:
                channel = REDIS_CHANNEL_VENUE_FEED.format(place_id=place_id)
                await self._pubsub.subscribe(channel)
                logger.debug(f"Subscribed to Redis channel for venue feed {place_id}")
            except Exception as e:
                logger.warning(f"Failed to subscribe to venue feed channel: {e}")

    def disconnect_venue_feed(self, websocket: WebSocket, place_id: str):
        """Remove a WebSocket from venue feed tracking"""
        if place_id in self.venue_feed_connections:
            if websocket in self.venue_feed_connections[place_id]:
                self.venue_feed_connections[place_id].remove(websocket)
            if not self.venue_feed_connections[place_id]:
                del self.venue_feed_connections[place_id]
                if self._pubsub is not None:
                    asyncio.create_task(self._unsubscribe_venue_feed(place_id))

    async def _unsubscribe_venue_feed(self, place_id: str):
        try:
            channel = REDIS_CHANNEL_VENUE_FEED.format(place_id=place_id)
            await self._pubsub.unsubscribe(channel)
            logger.debug(f"Unsubscribed from Redis channel for venue feed {place_id}")
        except Exception as e:
            logger.warning(f"Failed to unsubscribe from venue feed channel: {e}")

    async def _send_to_venue_feed_local(self, place_id: str, message: dict):
        """Send to all local connections for a venue feed"""
        dead_connections = []
        for ws in self.venue_feed_connections.get(place_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.append(ws)
        for ws in dead_connections:
            self.disconnect_venue_feed(ws, place_id)

    async def send_to_venue_feed(self, place_id: str, message: dict):
        """Send to all venue feed WebSockets across all instances via Redis"""
        try:
            redis = await get_redis()
            channel = REDIS_CHANNEL_VENUE_FEED.format(place_id=place_id)
            await redis.publish(channel, json.dumps(message))
        except Exception as e:
            logger.warning(f"Redis send_to_venue_feed failed, falling back to local: {e}")
            await self._send_to_venue_feed_local(place_id, message)

    async def start_subscriber(self):
        """Start Redis subscriber for cross-instance messages"""
        if self._subscriber_task is not None:
            return

        self._subscriber_task = asyncio.create_task(self._subscribe_loop())

    async def _subscribe_loop(self):
        """Subscribe to Redis channels and dispatch to local connections"""
        while True:
            try:
                redis = await get_redis()
                pubsub = redis.pubsub()
                self._pubsub = pubsub  # Store for dynamic subscriptions

                await pubsub.subscribe(REDIS_CHANNEL_BROADCAST)
                # Subscribe to user-specific channels for connected users
                for user_id in self.active_connections.keys():
                    await pubsub.subscribe(REDIS_CHANNEL_USER.format(user_id=user_id))
                # Subscribe to bounce channels for connected guests
                for bounce_id in self.bounce_connections.keys():
                    await pubsub.subscribe(REDIS_CHANNEL_BOUNCE.format(bounce_id=bounce_id))
                # Subscribe to venue feed channels
                for place_id in self.venue_feed_connections.keys():
                    await pubsub.subscribe(REDIS_CHANNEL_VENUE_FEED.format(place_id=place_id))

                logger.info(f"Redis subscriber started, subscribed to {len(self.active_connections)} user channels, {len(self.bounce_connections)} bounce channels, {len(self.venue_feed_connections)} venue feed channels")

                async for msg in pubsub.listen():
                    if msg["type"] != "message":
                        continue

                    try:
                        data = json.loads(msg["data"])
                        channel = msg["channel"]

                        if isinstance(channel, bytes):
                            channel = channel.decode('utf-8')

                        if channel == REDIS_CHANNEL_BROADCAST:
                            await self._send_local(data)
                        elif channel.startswith("ws:user:"):
                            user_id = int(channel.split(":")[-1])
                            await self._send_local(data, user_id)
                        elif channel.startswith("ws:venue_feed:"):
                            place_id = channel.split(":", 2)[-1]
                            await self._send_to_venue_feed_local(place_id, data)
                        elif channel.startswith("ws:bounce:"):
                            bounce_id = int(channel.split(":")[-1])
                            await self._send_to_bounce_local(bounce_id, data)
                    except Exception as e:
                        logger.error(f"Error processing Redis message: {e}")

            except Exception as e:
                logger.error(f"Redis subscriber error, reconnecting: {e}")
                self._pubsub = None
                await asyncio.sleep(1)


manager = ConnectionManager()


@router.websocket("/ws/notifications")
async def notifications_websocket(
    websocket: WebSocket,
    token: str = Query(...)
):
    """
    WebSocket endpoint for real-time in-app notifications.
    """
    from services.auth_service import decode_access_token
    from jose import JWTError

    # Validate token and get user_id (ensures it's an access token, not refresh)
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError) as e:
        logger.warning(f"WebSocket auth failed: {e}")
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect(websocket, user_id)
    logger.debug(f"WebSocket connected: user {user_id}")

    try:
        await websocket.send_json({"type": "connected", "user_id": user_id})

        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnected: user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
    finally:
        manager.disconnect(websocket, user_id)
