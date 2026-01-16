"""
Apple Push Notification Service (APNs) handler for Basel Radar
"""
import base64
import logging
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update
from sqlalchemy.sql import func

from core.config import settings
from db.models import DeviceToken, NotificationPreference

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    NEW_FOLLOWER = "new_follower"
    BOUNCE_INVITE = "bounce_invite"
    FOLLOW_BACK = "follow_back"
    FRIEND_AT_VENUE = "friend_at_venue"
    FRIEND_LEFT_VENUE = "friend_left_venue"
    CLOSE_FRIEND_CHECKIN = "close_friend_checkin"
    CLOSE_FRIEND_REQUEST = "close_friend_request"
    LOCATION_SHARE = "location_share"


@dataclass
class NotificationPayload:
    """Structured notification payload"""
    notification_type: NotificationType
    title: str
    body: str
    actor_id: int
    actor_nickname: str
    actor_profile_picture: Optional[str] = None
    bounce_id: Optional[int] = None
    bounce_venue_name: Optional[str] = None
    bounce_place_id: Optional[str] = None
    venue_place_id: Optional[str] = None
    venue_name: Optional[str] = None
    venue_latitude: Optional[float] = None
    venue_longitude: Optional[float] = None


class APNsService:
    """Apple Push Notification Service handler"""

    _instance: Optional['APNsService'] = None
    _client = None
    _initialized: bool = False

    @classmethod
    async def get_instance(cls) -> 'APNsService':
        if cls._instance is None:
            cls._instance = cls()
        if not cls._instance._initialized:
            await cls._instance._initialize()
        return cls._instance

    async def _initialize(self):
        """Initialize APNs client with credentials"""
        if not settings.APNS_KEY_BASE64:
            logger.warning("APNs key not configured - push notifications disabled")
            self._initialized = True
            return

        try:
            from aioapns import APNs
            import tempfile
            import os

            # Decode base64 key to string
            key_data = base64.b64decode(settings.APNS_KEY_BASE64).decode('utf-8')

            # Write key to temporary file (aioapns expects a file path)
            self._key_file = tempfile.NamedTemporaryFile(mode='w', suffix='.p8', delete=False)
            self._key_file.write(key_data)
            self._key_file.close()

            self._client = APNs(
                key=self._key_file.name,
                key_id=settings.APNS_KEY_ID,
                team_id=settings.APNS_TEAM_ID,
                topic=settings.APNS_BUNDLE_ID,
                use_sandbox=settings.APNS_USE_SANDBOX,
            )
            self._initialized = True
            logger.info(f"APNs client initialized (sandbox={settings.APNS_USE_SANDBOX})")
        except Exception as e:
            logger.error(f"Failed to initialize APNs client: {e}")
            self._client = None
            self._initialized = True

    def _notification_type_to_preference_field(self, notification_type: NotificationType) -> str:
        """Map notification type to preference field name"""
        mapping = {
            NotificationType.NEW_FOLLOWER: "new_followers",
            NotificationType.BOUNCE_INVITE: "bounce_invites",
            NotificationType.FOLLOW_BACK: "follow_backs",
            NotificationType.FRIEND_AT_VENUE: "friends_at_same_venue",
            NotificationType.FRIEND_LEFT_VENUE: "friends_leaving_venue",
            NotificationType.CLOSE_FRIEND_CHECKIN: "close_friend_checkins",
        }
        return mapping.get(notification_type, "push_enabled")

    async def _get_user_tokens(
        self,
        db: AsyncSession,
        user_id: int,
        notification_type: NotificationType
    ) -> List[str]:
        """Get active device tokens for user if notification type is enabled"""

        # Check user's notification preferences
        pref_result = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id
            )
        )
        preferences = pref_result.scalar_one_or_none()

        # If preferences exist, check if enabled
        if preferences:
            # Check master toggle
            if not preferences.push_enabled:
                logger.debug(f"Push disabled for user {user_id}")
                return []

            # Check specific notification type
            pref_field = self._notification_type_to_preference_field(notification_type)
            if not getattr(preferences, pref_field, True):
                logger.debug(f"Notification type {notification_type} disabled for user {user_id}")
                return []

        # Get active device tokens
        tokens_result = await db.execute(
            select(DeviceToken.device_token).where(
                and_(
                    DeviceToken.user_id == user_id,
                    DeviceToken.is_active == True
                )
            )
        )
        return [row[0] for row in tokens_result.all()]

    def _build_aps_payload(self, payload: NotificationPayload) -> Dict[str, Any]:
        """Build APNs payload with custom data"""

        # Custom data for app to process
        custom_data = {
            "notification_type": payload.notification_type.value,
            "actor": {
                "user_id": payload.actor_id,
                "nickname": payload.actor_nickname,
                "profile_picture": payload.actor_profile_picture,
            }
        }

        # Add bounce data if present
        if payload.bounce_id:
            custom_data["bounce"] = {
                "id": payload.bounce_id,
                "venue_name": payload.bounce_venue_name,
                "place_id": payload.bounce_place_id,
            }

        # Add venue data if present
        if payload.venue_place_id:
            custom_data["venue"] = {
                "place_id": payload.venue_place_id,
                "venue_name": payload.venue_name,
                "latitude": payload.venue_latitude,
                "longitude": payload.venue_longitude,
            }

        return {
            "aps": {
                "alert": {
                    "title": payload.title,
                    "body": payload.body,
                },
                "sound": "default",
                "badge": 1,
                "mutable-content": 1,
                "category": payload.notification_type.value,
            },
            "data": custom_data
        }

    async def send_notification(
        self,
        db: AsyncSession,
        user_id: int,
        payload: NotificationPayload
    ) -> bool:
        """Send push notification to a user's devices"""

        if not self._client:
            logger.warning("APNs client not initialized - skipping push")
            return False

        tokens = await self._get_user_tokens(db, user_id, payload.notification_type)
        logger.info(f"APNs: Found {len(tokens)} token(s) for user {user_id}")

        if not tokens:
            logger.warning(f"APNs: No active tokens for user {user_id} or notification disabled")
            return False

        aps_payload = self._build_aps_payload(payload)

        from aioapns import NotificationRequest, PushType

        success = False
        for token in tokens:
            try:
                request = NotificationRequest(
                    device_token=token,
                    message=aps_payload,
                    push_type=PushType.ALERT,
                )
                response = await self._client.send_notification(request)

                if response.is_successful:
                    logger.info(f"Push sent to user {user_id}, token {token[:20]}...")
                    success = True

                    # Update last_used_at
                    await db.execute(
                        update(DeviceToken)
                        .where(DeviceToken.device_token == token)
                        .values(last_used_at=datetime.now(timezone.utc))
                    )
                else:
                    logger.warning(f"Push failed for user {user_id}: {response.description}")

                    # Handle invalid tokens
                    if response.description in ['BadDeviceToken', 'Unregistered']:
                        await db.execute(
                            update(DeviceToken)
                            .where(DeviceToken.device_token == token)
                            .values(is_active=False)
                        )
                        logger.info(f"Deactivated invalid token for user {user_id}")

            except Exception as e:
                logger.error(f"Failed to send push to user {user_id}, token {token[:20]}...: {e}")

        await db.commit()
        return success

    async def send_to_multiple_users(
        self,
        db: AsyncSession,
        user_ids: List[int],
        payload: NotificationPayload
    ) -> Dict[int, bool]:
        """Send notification to multiple users"""
        results = {}
        for user_id in user_ids:
            results[user_id] = await self.send_notification(db, user_id, payload)
        return results


# Singleton accessor
async def get_apns_service() -> APNsService:
    return await APNsService.get_instance()
