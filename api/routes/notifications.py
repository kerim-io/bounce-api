"""
Notification API endpoints for device token management and preferences
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from db.database import get_async_session
from db.models import DeviceToken, NotificationPreference, User
from api.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


class RegisterDeviceRequest(BaseModel):
    device_token: str
    device_name: Optional[str] = None
    is_sandbox: bool = False


class NotificationPreferencesRequest(BaseModel):
    bounce_invites: Optional[bool] = None
    new_followers: Optional[bool] = None
    follow_backs: Optional[bool] = None
    friends_at_same_venue: Optional[bool] = None
    friends_leaving_venue: Optional[bool] = None
    close_friend_checkins: Optional[bool] = None
    push_enabled: Optional[bool] = None


class NotificationPreferencesResponse(BaseModel):
    bounce_invites: bool
    new_followers: bool
    follow_backs: bool
    friends_at_same_venue: bool
    friends_leaving_venue: bool
    close_friend_checkins: bool
    push_enabled: bool

    class Config:
        from_attributes = True


@router.post("/device-token")
async def register_device_token(
    request: RegisterDeviceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Register or update device token for push notifications"""
    logger.info(f"=== DEVICE TOKEN REGISTRATION ===")
    logger.info(f"User ID: {current_user.id}, Token: {request.device_token[:20]}..., Sandbox: {request.is_sandbox}")

    # Check if token already exists for this user
    result = await db.execute(
        select(DeviceToken).where(
            and_(
                DeviceToken.user_id == current_user.id,
                DeviceToken.device_token == request.device_token
            )
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing token
        existing.device_name = request.device_name
        existing.is_sandbox = request.is_sandbox
        existing.is_active = True
        existing.updated_at = datetime.now(timezone.utc)
    else:
        # Deactivate other tokens with the same device_token (for other users)
        # This handles the case where a device is signed out and signed in with different account
        await db.execute(
            DeviceToken.__table__.update()
            .where(DeviceToken.device_token == request.device_token)
            .values(is_active=False)
        )

        # Create new token entry
        device_token = DeviceToken(
            user_id=current_user.id,
            device_token=request.device_token,
            device_name=request.device_name,
            is_sandbox=request.is_sandbox,
            is_active=True
        )
        db.add(device_token)

    await db.commit()

    # Log all active tokens for this user after registration
    all_tokens = await db.execute(
        select(DeviceToken).where(
            and_(
                DeviceToken.user_id == current_user.id,
                DeviceToken.is_active == True
            )
        )
    )
    active_tokens = all_tokens.scalars().all()
    logger.info(f"Device token registered for user {current_user.id}: {request.device_token[:20]}... (sandbox={request.is_sandbox})")
    logger.info(f"User {current_user.id} now has {len(active_tokens)} active token(s)")
    for t in active_tokens:
        logger.info(f"  - Token: {t.device_token[:20]}... sandbox={t.is_sandbox} active={t.is_active}")

    return {"status": "success", "message": "Device token registered"}


@router.delete("/device-token")
async def unregister_device_token(
    device_token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Unregister device token (e.g., on logout)"""
    logger.info(f"=== DEVICE TOKEN UNREGISTER ===")
    logger.info(f"User {current_user.id} unregistering token: {device_token[:20] if len(device_token) > 20 else device_token}...")

    result = await db.execute(
        select(DeviceToken).where(
            and_(
                DeviceToken.user_id == current_user.id,
                DeviceToken.device_token == device_token
            )
        )
    )
    token = result.scalar_one_or_none()

    if token:
        token.is_active = False
        await db.commit()
        logger.info(f"Token deactivated for user {current_user.id}")
    else:
        logger.warning(f"Token not found for user {current_user.id} - nothing to unregister")

    return {"status": "success"}


@router.get("/preferences", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get user's notification preferences"""

    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.id
        )
    )
    prefs = result.scalar_one_or_none()

    if not prefs:
        # Return defaults
        return NotificationPreferencesResponse(
            bounce_invites=True,
            new_followers=True,
            follow_backs=True,
            friends_at_same_venue=True,
            friends_leaving_venue=True,
            close_friend_checkins=True,
            push_enabled=True
        )

    return NotificationPreferencesResponse(
        bounce_invites=prefs.bounce_invites,
        new_followers=prefs.new_followers,
        follow_backs=prefs.follow_backs,
        friends_at_same_venue=prefs.friends_at_same_venue,
        friends_leaving_venue=prefs.friends_leaving_venue,
        close_friend_checkins=prefs.close_friend_checkins,
        push_enabled=prefs.push_enabled
    )


@router.put("/preferences", response_model=NotificationPreferencesResponse)
async def update_notification_preferences(
    request: NotificationPreferencesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Update user's notification preferences"""

    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.id
        )
    )
    prefs = result.scalar_one_or_none()

    if not prefs:
        # Create new preferences
        prefs = NotificationPreference(user_id=current_user.id)
        db.add(prefs)

    # Update only provided fields
    update_data = request.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(prefs, field, value)

    prefs.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(prefs)

    return NotificationPreferencesResponse(
        bounce_invites=prefs.bounce_invites,
        new_followers=prefs.new_followers,
        follow_backs=prefs.follow_backs,
        friends_at_same_venue=prefs.friends_at_same_venue,
        friends_leaving_venue=prefs.friends_leaving_venue,
        close_friend_checkins=prefs.close_friend_checkins,
        push_enabled=prefs.push_enabled
    )


@router.post("/test-push")
async def test_push_notification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Send a test push notification to diagnose APNs issues"""
    from services.apns_service import get_apns_service, NotificationPayload, NotificationType
    from services.redis import increment_badge_count

    diagnostics = {}

    # 1. Check APNs service init
    try:
        apns = await get_apns_service()
        diagnostics["apns_initialized"] = apns._initialized
        diagnostics["has_private_key"] = apns._private_key is not None
        diagnostics["has_client"] = apns._client is not None
    except Exception as e:
        diagnostics["apns_init_error"] = str(e)
        return diagnostics

    # 2. Check device tokens
    tokens = await apns._get_user_tokens(db, current_user.id, NotificationType.BOUNCE_INVITE)
    diagnostics["active_tokens"] = len(tokens)
    diagnostics["tokens"] = [
        {"token": t.device_token[:20] + "...", "sandbox": t.is_sandbox, "active": t.is_active}
        for t in tokens
    ]

    if not tokens:
        diagnostics["error"] = "No active device tokens found"
        return diagnostics

    # 3. Try sending
    payload = NotificationPayload(
        notification_type=NotificationType.BOUNCE_INVITE,
        title="Test Push",
        body="If you see this, APNs is working",
        actor_id=current_user.id,
        actor_nickname=current_user.nickname or "Test",
        actor_profile_picture=None,
    )

    try:
        badge_count = await increment_badge_count(current_user.id)
        diagnostics["badge_count"] = badge_count
    except Exception as e:
        diagnostics["redis_error"] = str(e)
        badge_count = 1

    aps_payload = apns._build_aps_payload(payload, badge_count)
    diagnostics["aps_payload"] = aps_payload

    results = []
    for token in tokens:
        sent, error = await apns._send_to_token(token.device_token, token.is_sandbox, aps_payload)
        results.append({"token": token.device_token[:20] + "...", "sent": sent, "error": error})
    diagnostics["send_results"] = results

    return diagnostics


@router.post("/badge/reset")
async def reset_badge(
    current_user: User = Depends(get_current_user),
):
    """Reset badge count to 0 (called when app opens)"""
    from services.redis import reset_badge_count
    logger.info(f"Resetting badge count for user {current_user.id}")
    await reset_badge_count(current_user.id)
    return {"status": "success"}
