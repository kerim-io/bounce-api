from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import List, Dict
import json
import logging
from datetime import datetime, timezone

from db.database import create_async_session
from db.models import Post, User, Livestream, Like
from services.auth_service import decode_token

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


@router.websocket("/ws/feed")
async def websocket_feed(websocket: WebSocket, token: str = Query(...)):
    """
    WebSocket endpoint for real-time feed updates
    Connect with: ws://localhost:8001/ws/feed?token={jwt}
    """
    db = None
    user_id = None

    try:
        # Verify token
        payload = decode_token(token)
        user_id = int(payload.get("sub"))

        # Get user
        db = create_async_session()
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            await websocket.close(code=1008, reason="User not found")
            return

        # Accept connection
        await manager.connect(websocket, user_id)

        # Send initial feed with optimized query
        from sqlalchemy import case

        # Single optimized query with aggregations
        result = await db.execute(
            select(
                Post,
                User,
                func.count(Like.id).label('likes_count'),
                func.max(case((Like.user_id == user_id, 1), else_=0)).label('is_liked')
            )
            .join(User, Post.user_id == User.id)
            .outerjoin(Like, Post.id == Like.post_id)
            .group_by(Post.id, User.id)
            .order_by(desc(Post.created_at))
            .limit(50)
        )
        posts_data = result.all()

        # Build initial feed
        initial_feed = []
        for post, user, likes_count, is_liked in posts_data:
            initial_feed.append({
                "id": post.id,
                "user_id": post.user_id,
                "username": user.nickname,
                "content": post.content,
                "timestamp": post.created_at.isoformat(),
                "profile_pic_url": user.profile_picture,
                "media_url": post.media_url,
                "media_type": post.media_type,
                "latitude": post.latitude,
                "longitude": post.longitude,
                "venue_name": post.venue_name,
                "venue_id": post.venue_id,
                "likes_count": likes_count or 0,
                "is_liked_by_current_user": bool(is_liked)
            })

        await websocket.send_json({
            "type": "initial_feed",
            "posts": initial_feed
        })

        # Listen for messages
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                # Client disconnected normally - propagate to outer handler
                raise
            except json.JSONDecodeError as e:
                logger.warning("Invalid JSON received in WebSocket", extra={"user_id": user_id, "error": str(e)})
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format"
                })
                continue
            except Exception as e:
                logger.error("Error receiving WebSocket message", exc_info=True, extra={"user_id": user_id})
                break

            logger.debug("WebSocket received message", extra={"data": data, "user_id": user_id})

            # Validate message structure
            if not isinstance(data, dict):
                logger.warning("WebSocket message is not a dictionary", extra={"user_id": user_id})
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid message format: expected object"
                })
                continue

            message_type = data.get("type")
            if not message_type:
                logger.warning("WebSocket message missing type field", extra={"user_id": user_id})
                await websocket.send_json({
                    "type": "error",
                    "message": "Message must include 'type' field"
                })
                continue

            # Handle new post
            if message_type == "new_post":
                try:
                    content = data.get("content", "").strip()
                    media_url = data.get("media_url")

                    # Validate content - allow empty if media is present
                    if not content and not media_url:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Post must have content or media"
                        })
                        continue

                    # Validate content length (max 2000 chars)
                    if content and len(content) > 2000:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Post content exceeds maximum length of 2000 characters"
                        })
                        continue

                    # Validate coordinates if provided
                    latitude = data.get("latitude")
                    longitude = data.get("longitude")
                    if latitude is not None and longitude is not None:
                        try:
                            latitude = float(latitude)
                            longitude = float(longitude)
                            if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                                raise ValueError("Coordinates out of range")
                        except (TypeError, ValueError) as e:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Invalid latitude/longitude values"
                            })
                            continue

                    # Extract venue fields
                    venue_name = data.get("venue_name")
                    venue_id = data.get("venue_id")

                    # Create post
                    new_post = Post(
                        user_id=user_id,
                        content=content,
                        media_url=data.get("media_url"),
                        media_type=data.get("media_type"),
                        latitude=latitude,
                        longitude=longitude,
                        venue_name=venue_name,
                        venue_id=venue_id
                    )
                    db.add(new_post)
                    await db.commit()
                    await db.refresh(new_post)

                    # Get user for response
                    result = await db.execute(select(User).where(User.id == user_id))
                    post_user = result.scalar_one()

                    # Broadcast to all clients
                    post_data = {
                        "type": "new_post",
                        "post": {
                            "id": new_post.id,
                            "user_id": new_post.user_id,
                            "username": post_user.nickname,
                            "content": new_post.content,
                            "timestamp": new_post.created_at.isoformat(),
                            "profile_pic_url": post_user.profile_picture,
                            "media_url": new_post.media_url,
                            "media_type": new_post.media_type,
                            "latitude": new_post.latitude,
                            "longitude": new_post.longitude,
                            "venue_name": new_post.venue_name,
                            "venue_id": new_post.venue_id,
                            "likes_count": 0,
                            "is_liked_by_current_user": False
                        }
                    }
                    await manager.broadcast(post_data)
                except Exception as e:
                    logger.error("Error creating post via WebSocket", exc_info=True, extra={"user_id": user_id})
                    await websocket.send_json({
                        "type": "error",
                        "message": "Failed to create post"
                    })
            else:
                # Unknown message type
                logger.debug("Unknown WebSocket message type", extra={"user_id": user_id, "type": message_type})
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {message_type}"
                })

    except WebSocketDisconnect:
        if user_id:
            manager.disconnect(websocket, user_id)
    except Exception as e:
        logger.error("WebSocket error", exc_info=True, extra={"user_id": user_id, "error": str(e)})
        if user_id:
            manager.disconnect(websocket, user_id)
        await websocket.close(code=1011, reason="Internal server error")
    finally:
        if db:
            await db.close()


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
