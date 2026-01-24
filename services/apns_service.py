"""
Apple Push Notification Service (APNs) handler for Basel Radar
Uses httpx with HTTP/2 to avoid uvloop compatibility issues with aioapns
"""
import base64
import json
import logging
import time
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from core.config import settings
from db.models import DeviceToken, NotificationPreference

logger = logging.getLogger(__name__)

# APNs endpoints
APNS_PRODUCTION_URL = "https://api.push.apple.com"
APNS_SANDBOX_URL = "https://api.sandbox.push.apple.com"


class NotificationType(str, Enum):
    NEW_FOLLOWER = "new_follower"
    BOUNCE_INVITE = "bounce_invite"
    FOLLOW_BACK = "follow_back"
    FRIEND_AT_VENUE = "friend_at_venue"
    FRIEND_LEFT_VENUE = "friend_left_venue"
    CLOSE_FRIEND_CHECKIN = "close_friend_checkin"
    CLOSE_FRIEND_REQUEST = "close_friend_request"
    CLOSE_FRIEND_ACCEPTED = "close_friend_accepted"
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
    """Apple Push Notification Service handler using httpx HTTP/2"""

    _instance: Optional['APNsService'] = None
    _private_key = None
    _token: Optional[str] = None
    _token_timestamp: float = 0
    _initialized: bool = False
    _client: Optional[httpx.AsyncClient] = None

    @classmethod
    async def get_instance(cls) -> 'APNsService':
        if cls._instance is None:
            cls._instance = cls()
        if not cls._instance._initialized:
            await cls._instance._initialize()
        return cls._instance

    async def _initialize(self):
        """Initialize APNs with credentials"""
        if not settings.APNS_KEY_BASE64:
            logger.warning("APNs key not configured - push notifications disabled")
            self._initialized = True
            return

        try:
            # Decode base64 key (strip whitespace that Railway might add)
            key_b64 = settings.APNS_KEY_BASE64.strip().replace(" ", "").replace("\n", "")
            key_data = base64.b64decode(key_b64)

            # Check if PEM headers are present, if not wrap the raw key
            if not key_data.startswith(b"-----BEGIN"):
                # Raw key without PEM headers - wrap it
                key_b64_formatted = key_b64
                # Re-encode with proper PEM format
                key_data = (
                    b"-----BEGIN PRIVATE KEY-----\n" +
                    key_b64_formatted.encode() +
                    b"\n-----END PRIVATE KEY-----\n"
                )
                logger.info("APNs key wrapped with PEM headers")

            # Load the private key
            self._private_key = serialization.load_pem_private_key(
                key_data,
                password=None,
                backend=default_backend()
            )

            # Create HTTP/2 client
            self._client = httpx.AsyncClient(http2=True, timeout=30.0)

            self._initialized = True
            logger.info(f"APNs service initialized (sandbox={settings.APNS_USE_SANDBOX})")
        except Exception as e:
            logger.error(f"Failed to initialize APNs service: {e}")
            self._private_key = None
            self._initialized = True

    def _get_jwt_token(self) -> str:
        """Get or refresh JWT token for APNs authentication"""
        # Token is valid for 1 hour, refresh every 50 minutes
        current_time = time.time()
        if self._token and (current_time - self._token_timestamp) < 3000:
            return self._token

        # Create new token
        token_payload = {
            "iss": settings.APNS_TEAM_ID,
            "iat": int(current_time)
        }

        self._token = jwt.encode(
            token_payload,
            self._private_key,
            algorithm="ES256",
            headers={"kid": settings.APNS_KEY_ID}
        )
        self._token_timestamp = current_time
        logger.debug("Generated new APNs JWT token")
        return self._token

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
    ) -> List[DeviceToken]:
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
            select(DeviceToken).where(
                DeviceToken.user_id == user_id
            )
        )
        all_user_tokens = tokens_result.scalars().all()
        logger.info(f"APNs: User {user_id} has {len(all_user_tokens)} total token(s) in DB")
        for t in all_user_tokens:
            logger.info(f"APNs:   - Token: {t.device_token[:20]}... active={t.is_active} sandbox={t.is_sandbox}")

        active_tokens = [t for t in all_user_tokens if t.is_active]
        return active_tokens

    def _build_aps_payload(self, payload: NotificationPayload, badge_count: int = 1) -> Dict[str, Any]:
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
                "badge": badge_count,
                "mutable-content": 1,
                "category": payload.notification_type.value,
            },
            "data": custom_data
        }

    async def _send_to_token(self, token: str, is_sandbox: bool, aps_payload: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Send notification to a single device token"""
        if not self._client or not self._private_key:
            return False, "APNs not initialized"

        # Use the token's sandbox flag to determine which server to use
        base_url = APNS_SANDBOX_URL if is_sandbox else APNS_PRODUCTION_URL
        url = f"{base_url}/3/device/{token}"
        logger.info(f"APNs: Sending to {'SANDBOX' if is_sandbox else 'PRODUCTION'} server")

        headers = {
            "authorization": f"bearer {self._get_jwt_token()}",
            "apns-topic": settings.APNS_BUNDLE_ID,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }

        try:
            response = await self._client.post(
                url,
                json=aps_payload,
                headers=headers
            )

            if response.status_code == 200:
                return True, None
            else:
                # Parse error response
                try:
                    error_data = response.json()
                    reason = error_data.get("reason", "Unknown")
                except:
                    reason = f"HTTP {response.status_code}"
                return False, reason

        except Exception as e:
            logger.error(f"HTTP error sending to APNs: {e}")
            return False, str(e)

    async def send_notification(
        self,
        db: AsyncSession,
        user_id: int,
        payload: NotificationPayload
    ) -> bool:
        """Send push notification to a user's devices"""
        from services.redis import increment_badge_count

        if not self._private_key:
            logger.warning("APNs not initialized - skipping push")
            return False

        device_tokens = await self._get_user_tokens(db, user_id, payload.notification_type)
        logger.info(f"APNs: Found {len(device_tokens)} token(s) for user {user_id}")

        if not device_tokens:
            logger.warning(f"APNs: No active tokens for user {user_id} or notification disabled")
            return False

        # Increment badge count for user
        badge_count = await increment_badge_count(user_id)
        aps_payload = self._build_aps_payload(payload, badge_count)

        success = False
        for device_token in device_tokens:
            sent, error = await self._send_to_token(
                device_token.device_token,
                device_token.is_sandbox,
                aps_payload
            )

            if sent:
                logger.info(f"Push sent to user {user_id}, token {device_token.device_token[:20]}...")
                success = True

                # Update last_used_at
                await db.execute(
                    update(DeviceToken)
                    .where(DeviceToken.device_token == device_token.device_token)
                    .values(last_used_at=datetime.now(timezone.utc))
                )
            else:
                logger.warning(f"Push failed for user {user_id}: {error}")

                # Handle invalid tokens
                if error in ['BadDeviceToken', 'Unregistered', 'DeviceTokenNotForTopic']:
                    await db.execute(
                        update(DeviceToken)
                        .where(DeviceToken.device_token == device_token.device_token)
                        .values(is_active=False)
                    )
                    logger.info(f"Deactivated invalid token for user {user_id}")

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
