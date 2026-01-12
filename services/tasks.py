"""
Background task queue for non-blocking operations.
Uses RQ (Redis Queue) for task processing.
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from redis import Redis
from rq import Queue, Retry

from core.config import settings

logger = logging.getLogger(__name__)

# Redis connection for RQ (sync client, not async)
_redis_conn: Optional[Redis] = None
_notification_queue: Optional[Queue] = None


def get_notification_queue() -> Queue:
    """Get the notification queue (lazy initialization)"""
    global _redis_conn, _notification_queue
    if _notification_queue is None:
        _redis_conn = Redis.from_url(settings.REDIS_URL)
        _notification_queue = Queue('notifications', connection=_redis_conn)
    return _notification_queue


def enqueue_notification(user_id: int, payload_dict: Dict[str, Any]) -> None:
    """
    Enqueue a notification to be sent in the background.

    Args:
        user_id: Target user ID
        payload_dict: Serialized NotificationPayload as dict
    """
    try:
        queue = get_notification_queue()
        queue.enqueue(
            'services.tasks.send_notification_task',
            user_id,
            payload_dict,
            job_timeout=30,  # 30 second timeout per notification
            retry=Retry(max=3),  # Retry up to 3 times on failure
        )
        logger.debug(f"Enqueued notification for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to enqueue notification for user {user_id}: {e}")


def enqueue_notifications_bulk(user_ids: list, payload_dict: Dict[str, Any]) -> None:
    """
    Enqueue notifications for multiple users.

    Args:
        user_ids: List of target user IDs
        payload_dict: Serialized NotificationPayload as dict
    """
    for user_id in user_ids:
        enqueue_notification(user_id, payload_dict)


def send_notification_task(user_id: int, payload_dict: Dict[str, Any]) -> bool:
    """
    Worker task: Send a notification to a user.
    This runs in the RQ worker process (synchronous context).
    """
    # Run async code in sync context
    return asyncio.run(_send_notification_async(user_id, payload_dict))


async def _send_notification_async(user_id: int, payload_dict: Dict[str, Any]) -> bool:
    """Async implementation of notification sending"""
    from services.apns_service import get_apns_service, NotificationPayload, NotificationType
    from db.database import get_session_maker

    try:
        # Create a new database session for this task
        session_maker = get_session_maker()
        async with session_maker() as db:
            # Reconstruct the NotificationPayload from dict
            payload = NotificationPayload(
                notification_type=NotificationType(payload_dict['notification_type']),
                title=payload_dict['title'],
                body=payload_dict['body'],
                actor_id=payload_dict['actor_id'],
                actor_nickname=payload_dict['actor_nickname'],
                actor_profile_picture=payload_dict.get('actor_profile_picture'),
                bounce_id=payload_dict.get('bounce_id'),
                bounce_venue_name=payload_dict.get('bounce_venue_name'),
                bounce_place_id=payload_dict.get('bounce_place_id'),
                venue_place_id=payload_dict.get('venue_place_id'),
                venue_name=payload_dict.get('venue_name'),
                venue_latitude=payload_dict.get('venue_latitude'),
                venue_longitude=payload_dict.get('venue_longitude'),
            )

            apns = await get_apns_service()
            result = await apns.send_notification(db, user_id, payload)

            logger.info(f"Background notification sent to user {user_id}: {result}")
            return result

    except Exception as e:
        logger.error(f"Failed to send background notification to user {user_id}: {e}")
        raise  # Re-raise so RQ can retry


def payload_to_dict(payload) -> Dict[str, Any]:
    """Convert NotificationPayload to dict for queue serialization"""
    return {
        'notification_type': payload.notification_type.value,
        'title': payload.title,
        'body': payload.body,
        'actor_id': payload.actor_id,
        'actor_nickname': payload.actor_nickname,
        'actor_profile_picture': payload.actor_profile_picture,
        'bounce_id': payload.bounce_id,
        'bounce_venue_name': payload.bounce_venue_name,
        'bounce_place_id': payload.bounce_place_id,
        'venue_place_id': payload.venue_place_id,
        'venue_name': payload.venue_name,
        'venue_latitude': payload.venue_latitude,
        'venue_longitude': payload.venue_longitude,
    }


async def send_websocket_notification(user_id: int, payload_dict: Dict[str, Any]) -> bool:
    """
    Send in-app notification via WebSocket.
    Call this from the main server process (not from RQ worker).
    """
    from api.routes.websocket import manager

    try:
        ws_message = {
            "type": "notification",
            "notification_type": payload_dict['notification_type'],
            "message": payload_dict['body'],
            "actor": {
                "user_id": payload_dict['actor_id'],
                "nickname": payload_dict['actor_nickname'],
                "profile_picture": payload_dict.get('actor_profile_picture'),
            },
        }

        # Add bounce data if present
        if payload_dict.get('bounce_id'):
            ws_message["bounce"] = {
                "id": payload_dict['bounce_id'],
                "venue_name": payload_dict.get('bounce_venue_name'),
                "place_id": payload_dict.get('bounce_place_id'),
            }

        # Add venue data if present
        if payload_dict.get('venue_place_id'):
            ws_message["venue"] = {
                "place_id": payload_dict['venue_place_id'],
                "venue_name": payload_dict.get('venue_name'),
                "latitude": payload_dict.get('venue_latitude'),
                "longitude": payload_dict.get('venue_longitude'),
            }

        result = await manager.send_to_user(user_id, ws_message)
        logger.info(f"WebSocket notification sent to user {user_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"Failed to send WebSocket notification to user {user_id}: {e}")
        return False
