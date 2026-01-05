from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import List, Dict
import asyncio
import json
import logging
from datetime import datetime, timezone

from db.database import create_async_session
from db.models import Livestream
from services.redis import get_redis

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)

REDIS_CHANNEL_BROADCAST = "ws:broadcast"
REDIS_CHANNEL_USER = "ws:user:{user_id}"


class ConnectionManager:
    """WebSocket manager with Redis pub/sub for multi-instance support"""

    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self._subscriber_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

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

                await pubsub.subscribe(REDIS_CHANNEL_BROADCAST)
                # Subscribe to user-specific channels for connected users
                for user_id in self.active_connections.keys():
                    await pubsub.subscribe(REDIS_CHANNEL_USER.format(user_id=user_id))

                async for msg in pubsub.listen():
                    if msg["type"] != "message":
                        continue

                    try:
                        data = json.loads(msg["data"])
                        channel = msg["channel"]

                        if channel == REDIS_CHANNEL_BROADCAST:
                            await self._send_local(data)
                        elif channel.startswith("ws:user:"):
                            user_id = int(channel.split(":")[-1])
                            await self._send_local(data, user_id)
                    except Exception as e:
                        logger.error(f"Error processing Redis message: {e}")

            except Exception as e:
                logger.error(f"Redis subscriber error, reconnecting: {e}")
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
    import jwt
    from core.config import settings

    # Validate token and get user_id
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception as e:
        logger.warning(f"WebSocket auth failed: {e}")
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect(websocket, user_id)
    logger.info(f"WebSocket connected: user {user_id}")

    try:
        await websocket.send_json({"type": "connected", "user_id": user_id})

        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
    finally:
        manager.disconnect(websocket, user_id)


@router.websocket("/ws/livestream/{room_id}")
async def livestream_tracking_websocket(websocket: WebSocket, room_id: str):
    """
    WebSocket endpoint to track livestream connection status.
    When the connection drops, automatically end the livestream in the database.
    """
    await websocket.accept()

    db = create_async_session()
    try:
        # Send confirmation
        await websocket.send_json({"type": "connected", "room_id": room_id})

        # Keep connection alive and wait for disconnect
        while True:
            try:
                # Receive heartbeat or status messages
                data = await websocket.receive_json()

                # Validate message structure
                if not isinstance(data, dict):
                    logger.warning("Invalid message format in livestream WebSocket", extra={"room_id": room_id})
                    continue

                # Handle viewer count updates
                if data.get("type") == "viewer_update":
                    viewer_count = data.get("count")

                    if viewer_count is None:
                        logger.warning("Viewer update missing count field", extra={"room_id": room_id})
                        continue

                    try:
                        viewer_count = int(viewer_count)
                        if viewer_count < 0:
                            raise ValueError("Viewer count cannot be negative")
                    except (TypeError, ValueError) as e:
                        logger.warning("Invalid viewer count value", extra={"room_id": room_id, "count": viewer_count})
                        continue

                    result = await db.execute(
                        select(Livestream).where(
                            Livestream.room_id == room_id,
                            Livestream.status == 'active'
                        )
                    )
                    livestream = result.scalar_one_or_none()

                    if livestream:
                        if viewer_count > livestream.max_viewers:
                            livestream.max_viewers = viewer_count
                        await db.commit()

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError as e:
                logger.warning("Invalid JSON received in livestream WebSocket", extra={"room_id": room_id, "error": str(e)})
                continue
            except Exception as e:
                logger.error("Error handling livestream WebSocket message", exc_info=True, extra={"room_id": room_id})
                # Don't break - keep connection alive
                continue

    except Exception as e:
        logger.error("WebSocket error for livestream room", exc_info=True, extra={"room_id": room_id, "error": str(e)})

    finally:
        # Connection dropped - end the livestream
        try:
            result = await db.execute(
                select(Livestream).where(
                    Livestream.room_id == room_id,
                    Livestream.status == 'active'
                )
            )
            livestream = result.scalar_one_or_none()

            if livestream:
                livestream.ended_at = datetime.now(timezone.utc)
                livestream.status = 'ended'
                await db.commit()

                duration = livestream.duration_seconds
                logger.info(
                    "WebSocket disconnected - Livestream ended",
                    extra={"room_id": room_id, "duration_seconds": duration}
                )

        except Exception as e:
            logger.error("Error ending livestream on disconnect", exc_info=True, extra={"room_id": room_id, "error": str(e)})
        finally:
            await db.close()
