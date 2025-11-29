from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import List, Dict
import json
import logging
from datetime import datetime, timezone

from db.database import create_async_session
from db.models import Livestream

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def broadcast(self, message: dict):
        """Broadcast to all connected clients"""
        dead_connections = []
        for user_id, connections in self.active_connections.items():
            for connection in connections:
                try:
                    await connection.send_json(message)
                except Exception:
                    dead_connections.append((user_id, connection))

        # Clean up dead connections
        for user_id, connection in dead_connections:
            self.disconnect(connection, user_id)

    async def send_to_user(self, user_id: int, message: dict):
        """Send a message to a specific user"""
        if user_id not in self.active_connections:
            return False

        dead_connections = []
        for connection in self.active_connections[user_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(connection, user_id)

        return True


manager = ConnectionManager()


async def broadcast_location_update(location_id: str, latitude: float, longitude: float, area_name: str | None = None):
    """
    Broadcast anonymous location update to all connected clients

    Called when a user updates their location to notify map viewers in real-time.
    """
    await manager.broadcast({
        "type": "location_update",
        "location_id": location_id,
        "latitude": latitude,
        "longitude": longitude,
        "area_name": area_name,
        "timestamp": datetime.utcnow().isoformat()
    })


async def broadcast_location_expired(location_id: str):
    """
    Broadcast that a location has expired (15 min timeout)

    Tells clients to remove the marker from the map.
    """
    await manager.broadcast({
        "type": "location_expired",
        "location_id": location_id,
        "timestamp": datetime.utcnow().isoformat()
    })


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
