"""Core verification logic for Instagram 2FA"""

import json
import secrets
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.config import settings
from services.redis import get_redis
from db.models import User
from .models import PendingVerification, VerificationStatus

logger = logging.getLogger(__name__)

# Redis key patterns
KEY_VERIFY_USER = "ig_verify:{user_id}"
KEY_VERIFY_HANDLE = "ig_verify:handle:{handle}"


def normalize_handle(handle: str) -> str:
    """Normalize Instagram handle: lowercase, remove @ prefix"""
    return handle.lower().lstrip("@").strip()


def generate_code() -> str:
    """Generate a 6-digit verification code"""
    return str(secrets.randbelow(900000) + 100000)


async def request_verification(
    user_id: int,
    instagram_handle: str,
    client_id: str = "litapp",
    callback_url: Optional[str] = None
) -> PendingVerification:
    """
    Start a new Instagram verification request.

    Creates a pending verification in Redis, keyed by both user_id and handle.
    """
    redis = await get_redis()
    handle = normalize_handle(instagram_handle)

    # Check if this handle is already being verified by another user
    existing_user_id = await redis.get(KEY_VERIFY_HANDLE.format(handle=handle))
    if existing_user_id and int(existing_user_id) != user_id:
        raise ValueError(f"Handle @{handle} is already being verified by another user")

    # Create verification record
    verification = PendingVerification(
        client_id=client_id,
        user_id=user_id,
        instagram_handle=handle,
        verification_code=generate_code(),
        status=VerificationStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        callback_url=callback_url
    )

    # Store in Redis with TTL
    ttl = settings.IG_VERIFICATION_TTL
    user_key = KEY_VERIFY_USER.format(user_id=user_id)
    handle_key = KEY_VERIFY_HANDLE.format(handle=handle)

    await redis.setex(user_key, ttl, verification.model_dump_json())
    await redis.setex(handle_key, ttl, str(user_id))

    logger.info(f"Verification requested for user {user_id}, handle @{handle}")
    return verification


async def get_verification(user_id: int) -> Optional[PendingVerification]:
    """Get pending verification for a user"""
    redis = await get_redis()
    key = KEY_VERIFY_USER.format(user_id=user_id)
    data = await redis.get(key)

    if data:
        return PendingVerification.model_validate_json(data)
    return None


async def get_user_id_by_handle(handle: str) -> Optional[int]:
    """Get user_id for a pending verification by handle"""
    redis = await get_redis()
    handle = normalize_handle(handle)
    key = KEY_VERIFY_HANDLE.format(handle=handle)
    user_id = await redis.get(key)
    return int(user_id) if user_id else None


async def update_verification_status(
    user_id: int,
    status: VerificationStatus,
    dm_sent_at: Optional[datetime] = None
) -> Optional[PendingVerification]:
    """Update the status of a pending verification"""
    verification = await get_verification(user_id)
    if not verification:
        return None

    verification.status = status
    if dm_sent_at:
        verification.dm_sent_at = dm_sent_at

    redis = await get_redis()
    key = KEY_VERIFY_USER.format(user_id=user_id)
    ttl = await redis.ttl(key)
    if ttl > 0:
        await redis.setex(key, ttl, verification.model_dump_json())

    return verification


async def confirm_code(
    user_id: int,
    code: str,
    db: AsyncSession
) -> tuple[bool, str]:
    """
    Confirm a verification code.

    Returns (success, message) tuple.
    If successful, updates the User's instagram_handle in the database.
    """
    verification = await get_verification(user_id)

    if not verification:
        return False, "No pending verification found"

    if verification.status == VerificationStatus.VERIFIED:
        return False, "Already verified"

    if verification.status == VerificationStatus.PENDING:
        return False, "Verification code not yet sent. Please follow @litapp on Instagram first."

    if verification.verification_code != code:
        return False, "Invalid verification code"

    # Code matches - update user and mark as verified
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        return False, "User not found"

    # Update user's Instagram handle
    user.instagram_handle = verification.instagram_handle
    await db.commit()

    # Update verification status
    await update_verification_status(user_id, VerificationStatus.VERIFIED)

    # Clean up handle mapping
    redis = await get_redis()
    handle_key = KEY_VERIFY_HANDLE.format(handle=verification.instagram_handle)
    await redis.delete(handle_key)

    logger.info(f"Instagram verification completed for user {user_id}, handle @{verification.instagram_handle}")
    return True, f"Instagram account @{verification.instagram_handle} verified successfully"


async def cancel_verification(user_id: int) -> bool:
    """Cancel a pending verification"""
    verification = await get_verification(user_id)
    if not verification:
        return False

    redis = await get_redis()
    user_key = KEY_VERIFY_USER.format(user_id=user_id)
    handle_key = KEY_VERIFY_HANDLE.format(handle=verification.instagram_handle)

    await redis.delete(user_key)
    await redis.delete(handle_key)

    logger.info(f"Verification cancelled for user {user_id}")
    return True


async def get_all_pending_handles() -> dict[str, int]:
    """
    Get all pending verification handles mapped to user IDs.
    Used by the poller to match new followers.
    """
    redis = await get_redis()
    # Scan for all handle keys
    handles = {}
    async for key in redis.scan_iter(match="ig_verify:handle:*"):
        handle = key.replace("ig_verify:handle:", "")
        user_id = await redis.get(key)
        if user_id:
            handles[handle] = int(user_id)
    return handles
