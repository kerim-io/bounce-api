from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import logging
from datetime import datetime, timezone

from db.database import get_async_session, get_session_maker
from db.models import User, Follow, CheckIn
from api.dependencies import get_current_user
from api.routes.websocket import manager as ws_manager
from api.routes.users import SimpleUserResponse
from services.tasks import enqueue_notification, payload_to_dict
from api.routes.checkins import auto_checkout_if_needed

router = APIRouter(prefix="/users", tags=["close-friends"])
logger = logging.getLogger(__name__)

# Background task handle for silent push loop
_silent_push_task: Optional[asyncio.Task] = None


async def start_silent_push_loop():
    """Start background loop that sends silent pushes to users with active location sharing"""
    global _silent_push_task
    if _silent_push_task is not None:
        return
    _silent_push_task = asyncio.create_task(_silent_push_loop())
    logger.info("Started silent push loop for location sharing")


async def stop_silent_push_loop():
    """Stop the silent push background loop"""
    global _silent_push_task
    if _silent_push_task is not None:
        _silent_push_task.cancel()
        _silent_push_task = None
        logger.info("Stopped silent push loop")


async def _silent_push_loop():
    """Send silent push every 30 seconds to users who are sharing location with close friends"""
    from services.apns_service import get_apns_service

    while True:
        try:
            await asyncio.sleep(30)

            session_maker = get_session_maker()
            async with session_maker() as db:
                # Find all users who are actively sharing location with at least one close friend
                result = await db.execute(
                    select(Follow.follower_id).where(
                        Follow.close_friend_status == 'accepted',
                        Follow.is_sharing_location == True
                    ).distinct()
                )
                user_ids = [row[0] for row in result.all()]

                if not user_ids:
                    continue

                apns = await get_apns_service()
                for user_id in user_ids:
                    try:
                        await apns.send_silent_push(db, user_id)
                    except Exception as e:
                        logger.error(f"Silent push failed for user {user_id}: {e}")

                logger.debug(f"Sent silent pushes to {len(user_ids)} users sharing location")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Silent push loop error: {e}")
            await asyncio.sleep(5)


class CloseFriendLocationUpdate(BaseModel):
    latitude: float
    longitude: float


class CloseFriendLocationResponse(BaseModel):
    user_id: int
    nickname: Optional[str]
    profile_picture: Optional[str]
    latitude: float
    longitude: float
    updated_at: datetime
    checked_in_venue: Optional[str] = None  # Venue name if checked in


@router.get("/me/close-friend-requests")
async def get_pending_close_friend_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get list of pending close friend requests where others have requested to be close friends with the current user.
    """
    # Get all follows where someone else requested to be close friends with current user
    stmt = (
        select(Follow, User)
        .join(User, Follow.follower_id == User.id)
        .where(
            Follow.following_id == current_user.id,
            Follow.close_friend_status == 'pending',
            Follow.close_friend_requester_id != current_user.id
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    requests = []
    for follow, user in rows:
        requests.append({
            "user_id": user.id,
            "nickname": user.nickname,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "profile_picture": user.profile_picture or user.instagram_profile_pic,
            "requested_at": follow.created_at.isoformat() if follow.created_at else None
        })

    return {"requests": requests, "count": len(requests)}


@router.post("/follow/{user_id}/close-friend/request")
async def request_close_friend(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Request to become close friends with a user.
    Requires mutual follow. Sets status to 'pending' until the other user accepts.
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot add yourself as close friend")

    # Check if current user follows target user
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = result.scalar_one_or_none()

    if not follow:
        raise HTTPException(status_code=404, detail="Not following this user")

    # Check if it's a mutual follow
    reverse_result = await db.execute(
        select(Follow).where(
            Follow.follower_id == user_id,
            Follow.following_id == current_user.id
        )
    )
    reverse_follow = reverse_result.scalar_one_or_none()

    if not reverse_follow:
        raise HTTPException(
            status_code=400,
            detail="Close friend can only be set for mutual follows"
        )

    # Check current status
    if follow.close_friend_status == 'accepted':
        raise HTTPException(status_code=400, detail="Already close friends")

    if follow.close_friend_status == 'pending':
        raise HTTPException(status_code=400, detail="Request already pending")

    # Set status to pending on both follow records
    follow.close_friend_status = 'pending'
    follow.close_friend_requester_id = current_user.id
    reverse_follow.close_friend_status = 'pending'
    reverse_follow.close_friend_requester_id = current_user.id

    await db.commit()

    # Send WebSocket notification to the target user
    actor_name = current_user.nickname or current_user.first_name or "Someone"
    actor_pic = current_user.profile_picture or current_user.instagram_profile_pic

    notification_payload = {
        "type": "close_friend_request",
        "actor_id": current_user.id,
        "actor_nickname": actor_name,
        "actor_profile_picture": actor_pic,
        "message": f"{actor_name} wants to be close friends"
    }
    await ws_manager.send_to_user(user_id, notification_payload)

    # Also send push notification
    from services.apns_service import NotificationType, NotificationPayload
    payload = NotificationPayload(
        notification_type=NotificationType.CLOSE_FRIEND_REQUEST,
        title=actor_name,
        body="wants to be close friends",
        actor_id=current_user.id,
        actor_nickname=actor_name,
        actor_profile_picture=actor_pic
    )
    enqueue_notification(user_id, payload_to_dict(payload))

    return {
        "status": "success",
        "user_id": user_id,
        "close_friend_status": "pending"
    }


@router.post("/follow/{user_id}/close-friend/accept")
async def accept_close_friend(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Accept a close friend request from another user.
    """
    # Check if current user follows target user
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = result.scalar_one_or_none()

    if not follow:
        raise HTTPException(status_code=404, detail="Not following this user")

    # Check if there's a pending request from the other user
    if follow.close_friend_status != 'pending':
        raise HTTPException(status_code=400, detail="No pending close friend request")

    if follow.close_friend_requester_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot accept your own request")

    # Get reverse follow
    reverse_result = await db.execute(
        select(Follow).where(
            Follow.follower_id == user_id,
            Follow.following_id == current_user.id
        )
    )
    reverse_follow = reverse_result.scalar_one_or_none()

    # Set status to accepted on both follow records
    follow.close_friend_status = 'accepted'
    follow.is_close_friend = True
    if reverse_follow:
        reverse_follow.close_friend_status = 'accepted'
        reverse_follow.is_close_friend = True

    await db.commit()

    # Send WebSocket notification to the requester
    actor_name = current_user.nickname or current_user.first_name or "Someone"
    actor_pic = current_user.profile_picture or current_user.instagram_profile_pic

    notification_payload = {
        "type": "close_friend_accepted",
        "actor_id": current_user.id,
        "actor_nickname": actor_name,
        "actor_profile_picture": actor_pic,
        "message": f"{actor_name} accepted your close friend request"
    }
    await ws_manager.send_to_user(user_id, notification_payload)

    # Send push notification
    from services.apns_service import NotificationType, NotificationPayload
    payload = NotificationPayload(
        notification_type=NotificationType.CLOSE_FRIEND_ACCEPTED,
        title=actor_name,
        body="accepted your close friend request",
        actor_id=current_user.id,
        actor_nickname=actor_name,
        actor_profile_picture=actor_pic
    )
    enqueue_notification(user_id, payload_to_dict(payload))

    return {
        "status": "success",
        "user_id": user_id,
        "close_friend_status": "accepted"
    }


@router.post("/follow/{user_id}/close-friend/decline")
async def decline_close_friend(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Decline a close friend request from another user.
    """
    # Check if current user follows target user
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = result.scalar_one_or_none()

    if not follow:
        raise HTTPException(status_code=404, detail="Not following this user")

    # Check if there's a pending request
    if follow.close_friend_status != 'pending':
        raise HTTPException(status_code=400, detail="No pending close friend request")

    # Get reverse follow
    reverse_result = await db.execute(
        select(Follow).where(
            Follow.follower_id == user_id,
            Follow.following_id == current_user.id
        )
    )
    reverse_follow = reverse_result.scalar_one_or_none()

    # Reset status to none on both follow records
    follow.close_friend_status = 'none'
    follow.close_friend_requester_id = None
    if reverse_follow:
        reverse_follow.close_friend_status = 'none'
        reverse_follow.close_friend_requester_id = None

    await db.commit()

    # Send WebSocket notification to the requester
    notification_payload = {
        "type": "close_friend_declined",
        "actor_id": current_user.id,
        "actor_nickname": current_user.nickname or current_user.first_name or "Someone",
        "message": f"{current_user.nickname or current_user.first_name} declined your close friend request"
    }
    await ws_manager.send_to_user(user_id, notification_payload)

    return {
        "status": "success",
        "user_id": user_id,
        "close_friend_status": "none"
    }


@router.delete("/follow/{user_id}/close-friend")
async def remove_close_friend(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Remove close friend status. When either user removes, it removes for both.
    """
    # Check if current user follows target user
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = result.scalar_one_or_none()

    if not follow:
        raise HTTPException(status_code=404, detail="Not following this user")

    # Check if they are close friends or have pending request
    if follow.close_friend_status == 'none':
        raise HTTPException(status_code=400, detail="Not close friends")

    # Get reverse follow
    reverse_result = await db.execute(
        select(Follow).where(
            Follow.follower_id == user_id,
            Follow.following_id == current_user.id
        )
    )
    reverse_follow = reverse_result.scalar_one_or_none()

    # Reset status to none on both follow records
    follow.close_friend_status = 'none'
    follow.close_friend_requester_id = None
    follow.is_close_friend = False
    if reverse_follow:
        reverse_follow.close_friend_status = 'none'
        reverse_follow.close_friend_requester_id = None
        reverse_follow.is_close_friend = False

    await db.commit()

    # Send WebSocket notification to the other user
    notification_payload = {
        "type": "close_friend_removed",
        "actor_id": current_user.id,
        "actor_nickname": current_user.nickname or current_user.first_name or "Someone",
        "message": f"{current_user.nickname or current_user.first_name} removed you as close friend"
    }
    await ws_manager.send_to_user(user_id, notification_payload)

    return {
        "status": "success",
        "user_id": user_id,
        "close_friend_status": "none"
    }


@router.get("/follow/{user_id}/close-friend/status")
async def get_close_friend_status(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get the close friend status between current user and target user.
    """
    # Check if current user follows target user
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = result.scalar_one_or_none()

    if not follow:
        return {
            "user_id": user_id,
            "close_friend_status": "none",
            "requester_id": None,
            "is_requester": False
        }

    return {
        "user_id": user_id,
        "close_friend_status": follow.close_friend_status,
        "requester_id": follow.close_friend_requester_id,
        "is_requester": follow.close_friend_requester_id == current_user.id
    }


@router.post("/follow/{user_id}/location-sharing")
async def toggle_location_sharing(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Toggle location sharing with a close friend.
    When enabled, sends notification to the other user.
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot share location with yourself")

    # Check if current user follows target user
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = result.scalar_one_or_none()

    if not follow:
        raise HTTPException(status_code=404, detail="Not following this user")

    # Must be close friends to share location
    if follow.close_friend_status != 'accepted':
        raise HTTPException(status_code=400, detail="Must be close friends to share location")

    # Toggle location sharing
    new_state = not follow.is_sharing_location
    follow.is_sharing_location = new_state

    await db.commit()

    # If enabling location sharing, notify the other user
    if new_state:
        # Check if other user is sharing back
        reverse_result = await db.execute(
            select(Follow).where(
                Follow.follower_id == user_id,
                Follow.following_id == current_user.id
            )
        )
        reverse_follow = reverse_result.scalar_one_or_none()
        other_is_sharing = reverse_follow.is_sharing_location if reverse_follow else False

        # Send WebSocket notification
        notification_payload = {
            "type": "location_sharing_started",
            "actor_id": current_user.id,
            "actor_nickname": current_user.nickname or current_user.first_name or "Someone",
            "actor_profile_picture": current_user.profile_picture or current_user.instagram_profile_pic,
            "message": f"{current_user.nickname or current_user.first_name} started sharing their location with you",
            "is_requesting_share_back": not other_is_sharing
        }
        await ws_manager.send_to_user(user_id, notification_payload)

        # Send push notification
        from services.apns_service import NotificationType, NotificationPayload
        payload = NotificationPayload(
            notification_type=NotificationType.LOCATION_SHARE,
            title="Location Sharing",
            body=f"{current_user.nickname or current_user.first_name} started sharing their location with you",
            actor_id=current_user.id,
            actor_nickname=current_user.nickname or current_user.first_name or "Someone",
            actor_profile_picture=current_user.profile_picture or current_user.instagram_profile_pic
        )
        enqueue_notification(user_id, payload_to_dict(payload))
    else:
        # Notify that location sharing stopped
        notification_payload = {
            "type": "location_sharing_stopped",
            "actor_id": current_user.id,
            "actor_nickname": current_user.nickname or current_user.first_name or "Someone",
        }
        await ws_manager.send_to_user(user_id, notification_payload)

    return {
        "status": "success",
        "user_id": user_id,
        "is_sharing_location": new_state
    }


@router.get("/follow/{user_id}/location-sharing/status")
async def get_location_sharing_status(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get location sharing status between current user and target user.
    Returns whether each user is sharing their location with the other.
    """
    # Check if current user follows target user
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = result.scalar_one_or_none()

    # Check reverse follow
    reverse_result = await db.execute(
        select(Follow).where(
            Follow.follower_id == user_id,
            Follow.following_id == current_user.id
        )
    )
    reverse_follow = reverse_result.scalar_one_or_none()

    return {
        "user_id": user_id,
        "i_am_sharing": follow.is_sharing_location if follow else False,
        "they_are_sharing": reverse_follow.is_sharing_location if reverse_follow else False
    }


@router.post("/me/location/close-friends")
async def broadcast_location_to_close_friends(
    location: CloseFriendLocationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Broadcast current user's location to all close friends who have location sharing enabled.
    Only sends to close friends where:
    - We are sharing our location with them (our is_sharing_location = True)
    - The close friend relationship is accepted
    """
    # Update user's last location
    current_user.last_location_lat = location.latitude
    current_user.last_location_lon = location.longitude
    current_user.last_location_update = datetime.now(timezone.utc)
    await db.commit()

    # Auto-checkout from venue if user has moved far enough away
    await auto_checkout_if_needed(db, current_user.id, location.latitude, location.longitude)

    # Find all close friends we're sharing location with
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.close_friend_status == 'accepted',
            Follow.is_sharing_location == True
        )
    )
    follows = result.scalars().all()

    # Send location update to each close friend via WebSocket
    for follow in follows:
        location_payload = {
            "type": "close_friend_location",
            "user_id": current_user.id,
            "nickname": current_user.nickname or current_user.first_name,
            "profile_picture": current_user.profile_picture or current_user.instagram_profile_pic,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        await ws_manager.send_to_user(follow.following_id, location_payload)

    return {"status": "success", "recipients": len(follows)}


@router.get("/close-friends/locations", response_model=List[CloseFriendLocationResponse])
async def get_close_friend_locations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get locations of close friends who are sharing their location with you.
    Returns locations for close friends where:
    - They are sharing their location with you (their is_sharing_location = True)
    - They have a recent location update
    """
    logger.info(f"get_close_friend_locations called for user {current_user.id}")

    # Find close friends who are sharing their location with us
    # This means: they follow us AND have is_sharing_location = True
    result = await db.execute(
        select(User, Follow).join(
            Follow, Follow.follower_id == User.id
        ).where(
            Follow.following_id == current_user.id,
            Follow.close_friend_status == 'accepted',
            Follow.is_sharing_location == True,
            User.last_location_lat.isnot(None),
            User.last_location_lon.isnot(None)
        )
    )
    rows = result.all()
    logger.info(f"Found {len(rows)} close friends sharing location")

    # Get active check-ins for these users
    user_ids = [user.id for user, _ in rows]
    checkin_result = await db.execute(
        select(CheckIn).where(
            CheckIn.user_id.in_(user_ids),
            CheckIn.is_active == True
        )
    )
    active_checkins = {ci.user_id: ci for ci in checkin_result.scalars().all()}

    locations = []
    for user, follow in rows:
        checkin = active_checkins.get(user.id)
        locations.append(CloseFriendLocationResponse(
            user_id=user.id,
            nickname=user.nickname or user.first_name,
            profile_picture=user.profile_picture or user.instagram_profile_pic,
            latitude=user.last_location_lat,
            longitude=user.last_location_lon,
            updated_at=user.last_location_update,
            checked_in_venue=checkin.location_name if checkin else None
        ))

    return locations


@router.get("/me/close-friends", response_model=List[SimpleUserResponse])
async def get_close_friends(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get list of close friends (users you've marked as close friends)"""
    result = await db.execute(
        select(User, Follow).join(
            Follow, Follow.following_id == User.id
        ).where(
            Follow.follower_id == current_user.id,
            Follow.is_close_friend == True
        )
    )
    rows = result.all()

    return [
        SimpleUserResponse(
            id=user.id,
            nickname=user.nickname,
            first_name=user.first_name,
            last_name=user.last_name,
            profile_picture=user.profile_picture or user.instagram_profile_pic,
            employer=user.employer,
            instagram_handle=user.instagram_handle,
            is_close_friend=follow.is_close_friend,
            is_mutual=True  # Close friends are always mutual
        )
        for user, follow in rows
    ]
