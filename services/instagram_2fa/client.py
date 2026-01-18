"""Instagram client wrapper using instagrapi with session persistence"""

import json
import logging
from typing import Optional, Set
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired

from core.config import settings
from services.redis import get_redis

logger = logging.getLogger(__name__)

# Redis keys
REDIS_IG_SESSION = "ig_session"
REDIS_IG_FOLLOWERS = "ig_followers"


class InstagramClient:
    """Wrapper around instagrapi with session persistence to Redis"""

    def __init__(self):
        self._client: Optional[Client] = None
        self._logged_in = False

    async def _save_session(self) -> None:
        """Save session state to Redis"""
        if self._client:
            redis = await get_redis()
            session_data = self._client.get_settings()
            await redis.set(REDIS_IG_SESSION, json.dumps(session_data))
            logger.info("Instagram session saved to Redis")

    async def _load_session(self) -> bool:
        """Load session state from Redis. Returns True if loaded."""
        redis = await get_redis()
        session_json = await redis.get(REDIS_IG_SESSION)
        if session_json:
            try:
                session_data = json.loads(session_json)
                self._client = Client()
                self._client.set_settings(session_data)
                # Try to get user info to verify session is valid
                self._client.get_timeline_feed()
                logger.info("Instagram session loaded from Redis")
                return True
            except (LoginRequired, ChallengeRequired, Exception) as e:
                logger.warning(f"Saved session invalid, will re-login: {e}")
                self._client = None
        return False

    async def login(self) -> bool:
        """Login to Instagram, using cached session if available"""
        if self._logged_in and self._client:
            return True

        if not settings.IG_USERNAME or not settings.IG_PASSWORD:
            logger.error("Instagram credentials not configured")
            return False

        # Try loading existing session first
        if await self._load_session():
            self._logged_in = True
            return True

        # Fresh login
        try:
            self._client = Client()
            self._client.login(settings.IG_USERNAME, settings.IG_PASSWORD)
            await self._save_session()
            self._logged_in = True
            logger.info(f"Instagram login successful as {settings.IG_USERNAME}")
            return True
        except ChallengeRequired as e:
            logger.error(f"Instagram challenge required (2FA/verification needed): {e}")
            return False
        except Exception as e:
            logger.error(f"Instagram login failed: {e}")
            return False

    async def get_followers(self) -> Set[str]:
        """Get set of follower usernames (normalized lowercase)"""
        if not await self.login():
            return set()

        try:
            user_id = self._client.user_id
            followers = self._client.user_followers(user_id)
            # Return set of normalized usernames
            return {user.username.lower() for user in followers.values()}
        except Exception as e:
            logger.error(f"Failed to get followers: {e}")
            self._logged_in = False  # Force re-login on next attempt
            return set()

    async def get_follower_pks(self) -> Set[int]:
        """Get set of follower PKs (primary keys/user IDs)"""
        if not await self.login():
            return set()

        try:
            user_id = self._client.user_id
            followers = self._client.user_followers(user_id)
            return set(followers.keys())
        except Exception as e:
            logger.error(f"Failed to get follower PKs: {e}")
            self._logged_in = False
            return set()

    async def get_user_pk_by_username(self, username: str) -> Optional[int]:
        """Get user PK by username"""
        if not await self.login():
            return None

        try:
            user = self._client.user_info_by_username(username)
            return user.pk
        except Exception as e:
            logger.warning(f"Failed to get user PK for {username}: {e}")
            return None

    async def send_dm(self, user_pk: int, message: str) -> bool:
        """Send a DM to a user by their PK"""
        if not await self.login():
            return False

        try:
            self._client.direct_send(message, [user_pk])
            logger.info(f"DM sent to user PK {user_pk}")
            return True
        except Exception as e:
            logger.error(f"Failed to send DM to {user_pk}: {e}")
            return False

    async def send_dm_by_username(self, username: str, message: str) -> bool:
        """Send a DM to a user by their username"""
        user_pk = await self.get_user_pk_by_username(username)
        if user_pk:
            return await self.send_dm(user_pk, message)
        return False

    async def get_known_followers(self) -> Set[int]:
        """Get the cached set of known follower PKs from Redis"""
        redis = await get_redis()
        members = await redis.smembers(REDIS_IG_FOLLOWERS)
        return {int(pk) for pk in members} if members else set()

    async def update_known_followers(self, follower_pks: Set[int]) -> None:
        """Update the cached set of known followers in Redis"""
        redis = await get_redis()
        if follower_pks:
            # Clear and re-add all followers
            await redis.delete(REDIS_IG_FOLLOWERS)
            await redis.sadd(REDIS_IG_FOLLOWERS, *[str(pk) for pk in follower_pks])

    async def get_new_followers(self) -> Set[int]:
        """Get PKs of new followers since last check"""
        current_followers = await self.get_follower_pks()
        if not current_followers:
            return set()

        known_followers = await self.get_known_followers()
        new_followers = current_followers - known_followers

        # Update known followers
        await self.update_known_followers(current_followers)

        return new_followers

    async def get_username_by_pk(self, user_pk: int) -> Optional[str]:
        """Get username by user PK"""
        if not await self.login():
            return None

        try:
            user = self._client.user_info(user_pk)
            return user.username.lower()
        except Exception as e:
            logger.warning(f"Failed to get username for PK {user_pk}: {e}")
            return None


# Singleton instance
_ig_client: Optional[InstagramClient] = None


async def get_ig_client() -> InstagramClient:
    """Get the Instagram client singleton"""
    global _ig_client
    if _ig_client is None:
        _ig_client = InstagramClient()
    return _ig_client
