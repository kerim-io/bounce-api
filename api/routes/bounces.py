from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_, and_
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import json
import logging

from db.database import get_async_session
from db.models import Bounce, BounceInvite, BounceAttendee, User, Place, GooglePic
from api.dependencies import get_current_user
from services.geofence import haversine_distance
from services.places import get_place_with_photos
from services.places.autocomplete import index_place as index_place_to_cache, increment_bounce_count
from api.routes.websocket import manager
from services.apns_service import NotificationPayload, NotificationType
from services.cache import cache_get, cache_set, cache_delete
from services.tasks import enqueue_notification, payload_to_dict

router = APIRouter(prefix="/bounces", tags=["bounces"])
logger = logging.getLogger(__name__)

# Attendees are considered "present" if seen within this time window
ATTENDEE_EXPIRY_MINUTES = 15
# Proximity radius for auto-checkin (in km)
BOUNCE_PROXIMITY_KM = 0.1  # 100 meters


async def get_active_attendees(
    db: AsyncSession,
    bounce_id: int,
    include_details: bool = True
) -> tuple[int, List["AttendeeInfo"]]:
    """
    Get active attendees for a bounce (seen within last 15 minutes).
    Returns (count, attendee_list).
    """
    expiry_time = datetime.now(timezone.utc) - timedelta(minutes=ATTENDEE_EXPIRY_MINUTES)

    if include_details:
        stmt = (
            select(BounceAttendee, User)
            .join(User, BounceAttendee.user_id == User.id)
            .where(
                BounceAttendee.bounce_id == bounce_id,
                BounceAttendee.last_seen_at >= expiry_time
            )
            .order_by(BounceAttendee.joined_at.asc())
        )
        result = await db.execute(stmt)
        rows = result.all()

        attendees = [
            AttendeeInfo(
                user_id=att.user_id,
                nickname=user.nickname,
                profile_picture=user.profile_picture or user.instagram_profile_pic,
                joined_at=att.joined_at
            )
            for att, user in rows
        ]
        return len(attendees), attendees
    else:
        stmt = (
            select(func.count(BounceAttendee.id))
            .where(
                BounceAttendee.bounce_id == bounce_id,
                BounceAttendee.last_seen_at >= expiry_time
            )
        )
        result = await db.execute(stmt)
        count = result.scalar() or 0
        return count, []


# Request/Response Schemas
class BounceCreate(BaseModel):
    venue_name: str
    venue_address: Optional[str] = None
    latitude: float
    longitude: float
    place_id: Optional[str] = None  # Google Places ID for storing place data
    bounce_time: datetime
    is_now: bool = False
    is_public: bool = False
    invite_user_ids: Optional[List[int]] = None


class AttendeeInfo(BaseModel):
    user_id: int
    nickname: Optional[str]
    profile_picture: Optional[str]
    joined_at: datetime


class BounceResponse(BaseModel):
    id: int
    creator_id: int
    creator_nickname: Optional[str]
    creator_profile_pic: Optional[str]
    venue_name: str
    venue_address: Optional[str]
    latitude: float
    longitude: float
    place_id: Optional[str] = None
    bounce_time: datetime
    is_now: bool
    is_public: bool
    status: str
    invite_count: int
    attendee_count: int = 0
    attendees: Optional[List[AttendeeInfo]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class InviteRequest(BaseModel):
    user_ids: List[int]


# Endpoints
@router.post("/", response_model=BounceResponse, status_code=status.HTTP_201_CREATED)
async def create_bounce(
    bounce_data: BounceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Create a new bounce with optional invites"""
    try:
        # Store/link the place if place_id is provided
        places_fk_id = None
        if bounce_data.place_id:
            place = await get_place_with_photos(
                db=db,
                place_id=bounce_data.place_id,
                venue_name=bounce_data.venue_name,
                venue_address=bounce_data.venue_address,
                latitude=bounce_data.latitude,
                longitude=bounce_data.longitude
            )
            if place:
                places_fk_id = place.id
                logger.info(f"Linked bounce to place {place.id} ({place.place_id})")

                # Index place to global Redis cache for autocomplete/nearby search
                types_list = json.loads(place.types) if place.types else []
                # Get first photo URL from place's photos relationship
                photo_url = None
                if place.photos:
                    photo_url = place.photos[0].photo_url
                await index_place_to_cache(
                    place_id=place.place_id,
                    name=place.name,
                    address=place.address or "",
                    lat=place.latitude,
                    lng=place.longitude,
                    types=types_list,
                    bounce_count=place.bounce_count,
                    photo_url=photo_url
                )
                # Increment bounce count in Redis cache
                await increment_bounce_count(place.place_id)

        # Create the bounce
        bounce = Bounce(
            creator_id=current_user.id,
            places_fk_id=places_fk_id,
            venue_name=bounce_data.venue_name,
            venue_address=bounce_data.venue_address,
            latitude=bounce_data.latitude,
            longitude=bounce_data.longitude,
            place_id=bounce_data.place_id,
            bounce_time=bounce_data.bounce_time,
            is_now=bounce_data.is_now,
            is_public=bounce_data.is_public
        )
        db.add(bounce)
        await db.flush()  # Get the bounce ID

        # Add invites if provided
        invite_count = 0
        if bounce_data.invite_user_ids:
            for user_id in bounce_data.invite_user_ids:
                if user_id != current_user.id:  # Don't invite yourself
                    invite = BounceInvite(bounce_id=bounce.id, user_id=user_id)
                    db.add(invite)
                    invite_count += 1

        await db.commit()
        await db.refresh(bounce)

        logger.info(
            "Bounce created",
            extra={
                "bounce_id": bounce.id,
                "creator_id": current_user.id,
                "venue": bounce.venue_name,
                "is_public": bounce.is_public,
                "invite_count": invite_count
            }
        )

        # Build response
        # Use profile_picture if set, otherwise fallback to instagram_profile_pic
        profile_pic = current_user.profile_picture or current_user.instagram_profile_pic
        bounce_response = BounceResponse(
            id=bounce.id,
            creator_id=bounce.creator_id,
            creator_nickname=current_user.nickname,
            creator_profile_pic=profile_pic,
            venue_name=bounce.venue_name,
            venue_address=bounce.venue_address,
            latitude=bounce.latitude,
            longitude=bounce.longitude,
            place_id=bounce.place_id,
            bounce_time=bounce.bounce_time,
            is_now=bounce.is_now,
            is_public=bounce.is_public,
            status=bounce.status,
            invite_count=invite_count,
            created_at=bounce.created_at
        )

        # Broadcast via WebSocket
        invited_ids = bounce_data.invite_user_ids or []
        ws_message = {
            "type": "new_bounce",
            "bounce": bounce_response.model_dump(mode='json'),
            "invited_user_ids": invited_ids
        }

        # If public, broadcast to everyone; otherwise only to invited users
        if bounce.is_public:
            await manager.broadcast(ws_message)
        else:
            # Send to creator and invited users only
            for user_id in [current_user.id] + invited_ids:
                if user_id in manager.active_connections:
                    for conn in manager.active_connections[user_id]:
                        try:
                            await conn.send_json(ws_message)
                        except Exception:
                            pass

        # Queue push notifications to invited users (non-blocking)
        for user_id in invited_ids:
            payload = NotificationPayload(
                notification_type=NotificationType.BOUNCE_INVITE,
                title="Bounce Invite",
                body=f"{current_user.nickname or current_user.first_name} invited you to bounce at {bounce.venue_name}",
                actor_id=current_user.id,
                actor_nickname=current_user.nickname or current_user.first_name or "Someone",
                actor_profile_picture=current_user.profile_picture or current_user.instagram_profile_pic,
                bounce_id=bounce.id,
                bounce_venue_name=bounce.venue_name,
                bounce_place_id=bounce.place_id
            )
            enqueue_notification(user_id, payload_to_dict(payload))

        return bounce_response

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create bounce: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create bounce"
        )


@router.get("/", response_model=List[BounceResponse])
async def get_bounces(
    status_filter: Optional[str] = "active",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get bounces: ones I created + ones I'm invited to + public ones"""

    # Subquery for invite count
    invite_count_subq = (
        select(func.count(BounceInvite.id))
        .where(BounceInvite.bounce_id == Bounce.id)
        .correlate(Bounce)
        .scalar_subquery()
    )

    # Build query - bounces I created, I'm invited to, or are public
    invited_bounce_ids = (
        select(BounceInvite.bounce_id)
        .where(BounceInvite.user_id == current_user.id)
    )

    stmt = (
        select(Bounce, User, invite_count_subq.label('invite_count'))
        .join(User, Bounce.creator_id == User.id)
        .where(
            or_(
                Bounce.creator_id == current_user.id,  # My bounces
                Bounce.id.in_(invited_bounce_ids),      # Invited to
                Bounce.is_public == True                # Public bounces
            )
        )
    )

    # Filter by status
    if status_filter:
        stmt = stmt.where(Bounce.status == status_filter)

    stmt = stmt.order_by(desc(Bounce.bounce_time))

    result = await db.execute(stmt)
    rows = result.all()

    return [
        BounceResponse(
            id=bounce.id,
            creator_id=bounce.creator_id,
            creator_nickname=user.nickname,
            creator_profile_pic=user.profile_picture or user.instagram_profile_pic,
            venue_name=bounce.venue_name,
            venue_address=bounce.venue_address,
            latitude=bounce.latitude,
            longitude=bounce.longitude,
            place_id=bounce.place_id,
            bounce_time=bounce.bounce_time,
            is_now=bounce.is_now,
            is_public=bounce.is_public,
            status=bounce.status,
            invite_count=invite_count or 0,
            created_at=bounce.created_at
        )
        for bounce, user, invite_count in rows
    ]


@router.get("/map", response_model=List[BounceResponse])
async def get_map_bounces(
    lat: float,
    lng: float,
    radius: float = 50.0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get all bounces visible to the user for map display.

    Returns:
    - All public bounces within radius
    - All bounces user is invited to (regardless of distance)
    - All bounces user created (regardless of distance)

    Args:
        lat: User's latitude
        lng: User's longitude
        radius: Search radius in km for public bounces (default 50km)
    """
    now = datetime.now(timezone.utc)

    invite_count_subq = (
        select(func.count(BounceInvite.id))
        .where(BounceInvite.bounce_id == Bounce.id)
        .correlate(Bounce)
        .scalar_subquery()
    )

    # Get IDs of bounces user is invited to
    invited_bounce_ids = (
        select(BounceInvite.bounce_id)
        .where(BounceInvite.user_id == current_user.id)
    )

    # Get all active bounces that are:
    # - public, OR
    # - user is invited to, OR
    # - user created
    stmt = (
        select(Bounce, User, invite_count_subq.label('invite_count'))
        .join(User, Bounce.creator_id == User.id)
        .where(Bounce.status == 'active')
        .where(
            or_(
                Bounce.is_public == True,
                Bounce.id.in_(invited_bounce_ids),
                Bounce.creator_id == current_user.id
            )
        )
        .order_by(Bounce.bounce_time.asc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Filter: public bounces must be within radius, private ones always included
    visible_bounces = []
    seen_ids = set()

    for bounce, user, invite_count in rows:
        if bounce.id in seen_ids:
            continue
        seen_ids.add(bounce.id)

        # Check if this bounce should be visible
        is_mine = bounce.creator_id == current_user.id
        is_invited = not bounce.is_public and not is_mine  # If we got it and it's not public/mine, we're invited

        if bounce.is_public and not is_mine:
            # Public bounce - check distance
            distance = haversine_distance(lat, lng, bounce.latitude, bounce.longitude)
            if distance > radius:
                continue

        # Get attendee info for public "now" bounces
        attendee_count = 0
        attendees = None
        if bounce.is_public and bounce.is_now:
            attendee_count, attendees = await get_active_attendees(db, bounce.id, include_details=True)

        visible_bounces.append(
            BounceResponse(
                id=bounce.id,
                creator_id=bounce.creator_id,
                creator_nickname=user.nickname,
                creator_profile_pic=user.profile_picture or user.instagram_profile_pic,
                venue_name=bounce.venue_name,
                venue_address=bounce.venue_address,
                latitude=bounce.latitude,
                longitude=bounce.longitude,
                place_id=bounce.place_id,
                bounce_time=bounce.bounce_time,
                is_now=bounce.is_now,
                is_public=bounce.is_public,
                status=bounce.status,
                invite_count=invite_count or 0,
                attendee_count=attendee_count,
                attendees=attendees,
                created_at=bounce.created_at
            )
        )

    return visible_bounces


@router.get("/mine", response_model=List[BounceResponse])
async def get_my_bounces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get bounces created by the current user"""
    invite_count_subq = (
        select(func.count(BounceInvite.id))
        .where(BounceInvite.bounce_id == Bounce.id)
        .correlate(Bounce)
        .scalar_subquery()
    )

    stmt = (
        select(Bounce, User, invite_count_subq.label('invite_count'))
        .join(User, Bounce.creator_id == User.id)
        .where(Bounce.creator_id == current_user.id)
        .order_by(desc(Bounce.bounce_time))
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        BounceResponse(
            id=bounce.id,
            creator_id=bounce.creator_id,
            creator_nickname=user.nickname,
            creator_profile_pic=user.profile_picture or user.instagram_profile_pic,
            venue_name=bounce.venue_name,
            venue_address=bounce.venue_address,
            latitude=bounce.latitude,
            longitude=bounce.longitude,
            place_id=bounce.place_id,
            bounce_time=bounce.bounce_time,
            is_now=bounce.is_now,
            is_public=bounce.is_public,
            status=bounce.status,
            invite_count=invite_count or 0,
            created_at=bounce.created_at
        )
        for bounce, user, invite_count in rows
    ]


@router.get("/invited", response_model=List[BounceResponse])
async def get_invited_bounces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get bounces the current user is invited to"""
    invite_count_subq = (
        select(func.count(BounceInvite.id))
        .where(BounceInvite.bounce_id == Bounce.id)
        .correlate(Bounce)
        .scalar_subquery()
    )

    # Get bounces where user is invited
    stmt = (
        select(Bounce, User, invite_count_subq.label('invite_count'))
        .join(User, Bounce.creator_id == User.id)
        .join(BounceInvite, Bounce.id == BounceInvite.bounce_id)
        .where(BounceInvite.user_id == current_user.id)
        .where(Bounce.status == 'active')
        .order_by(Bounce.bounce_time.asc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        BounceResponse(
            id=bounce.id,
            creator_id=bounce.creator_id,
            creator_nickname=user.nickname,
            creator_profile_pic=user.profile_picture or user.instagram_profile_pic,
            venue_name=bounce.venue_name,
            venue_address=bounce.venue_address,
            latitude=bounce.latitude,
            longitude=bounce.longitude,
            place_id=bounce.place_id,
            bounce_time=bounce.bounce_time,
            is_now=bounce.is_now,
            is_public=bounce.is_public,
            status=bounce.status,
            invite_count=invite_count or 0,
            created_at=bounce.created_at
        )
        for bounce, user, invite_count in rows
    ]


@router.get("/public", response_model=List[BounceResponse])
async def get_public_bounces(
    lat: float,
    lng: float,
    radius: float = 10.0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get nearby public bounces.

    Args:
        lat: User's latitude
        lng: User's longitude
        radius: Search radius in km (default 10km)
    """
    now = datetime.now(timezone.utc)

    invite_count_subq = (
        select(func.count(BounceInvite.id))
        .where(BounceInvite.bounce_id == Bounce.id)
        .correlate(Bounce)
        .scalar_subquery()
    )

    # Get all public active future bounces
    stmt = (
        select(Bounce, User, invite_count_subq.label('invite_count'))
        .join(User, Bounce.creator_id == User.id)
        .where(Bounce.is_public == True)
        .where(Bounce.status == 'active')
        .where(Bounce.bounce_time >= now)
        .order_by(Bounce.bounce_time.asc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Filter by distance using haversine
    nearby_bounces = []
    for bounce, user, invite_count in rows:
        distance = haversine_distance(lat, lng, bounce.latitude, bounce.longitude)
        if distance <= radius:
            nearby_bounces.append(
                BounceResponse(
                    id=bounce.id,
                    creator_id=bounce.creator_id,
                    creator_nickname=user.nickname,
                    creator_profile_pic=user.profile_picture or user.instagram_profile_pic,
                    venue_name=bounce.venue_name,
                    venue_address=bounce.venue_address,
                    latitude=bounce.latitude,
                    longitude=bounce.longitude,
                    place_id=bounce.place_id,
                    bounce_time=bounce.bounce_time,
                    is_now=bounce.is_now,
                    is_public=bounce.is_public,
                    status=bounce.status,
                    invite_count=invite_count or 0,
                    created_at=bounce.created_at
                )
            )

    return nearby_bounces


@router.get("/{bounce_id}", response_model=BounceResponse)
async def get_bounce(
    bounce_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get a single bounce by ID"""

    # Check if user has access (creator, invited, or public)
    invited_check = await db.execute(
        select(BounceInvite).where(
            BounceInvite.bounce_id == bounce_id,
            BounceInvite.user_id == current_user.id
        )
    )
    is_invited = invited_check.scalar_one_or_none() is not None

    # Get bounce with creator info
    stmt = (
        select(Bounce, User)
        .join(User, Bounce.creator_id == User.id)
        .where(Bounce.id == bounce_id)
    )
    result = await db.execute(stmt)
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Bounce not found")

    bounce, user = row

    # Check access
    if not (bounce.is_public or bounce.creator_id == current_user.id or is_invited):
        raise HTTPException(status_code=403, detail="Access denied")

    # Get invite count
    count_result = await db.execute(
        select(func.count(BounceInvite.id)).where(BounceInvite.bounce_id == bounce_id)
    )
    invite_count = count_result.scalar() or 0

    return BounceResponse(
        id=bounce.id,
        creator_id=bounce.creator_id,
        creator_nickname=user.nickname,
        creator_profile_pic=user.profile_picture or user.instagram_profile_pic,
        venue_name=bounce.venue_name,
        venue_address=bounce.venue_address,
        latitude=bounce.latitude,
        longitude=bounce.longitude,
        place_id=bounce.place_id,
        bounce_time=bounce.bounce_time,
        is_now=bounce.is_now,
        is_public=bounce.is_public,
        status=bounce.status,
        invite_count=invite_count,
        created_at=bounce.created_at
    )


@router.delete("/{bounce_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bounce(
    bounce_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Delete a bounce (creator only)"""

    result = await db.execute(
        select(Bounce).where(Bounce.id == bounce_id)
    )
    bounce = result.scalar_one_or_none()

    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found")

    if bounce.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the creator can delete this bounce")

    await db.delete(bounce)
    await db.commit()

    logger.info(f"Bounce {bounce_id} deleted by user {current_user.id}")


@router.post("/{bounce_id}/invite", status_code=status.HTTP_201_CREATED)
async def invite_to_bounce(
    bounce_id: int,
    invite_data: InviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Invite users to a bounce (creator only)"""

    result = await db.execute(
        select(Bounce).where(Bounce.id == bounce_id)
    )
    bounce = result.scalar_one_or_none()

    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found")

    if bounce.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the creator can invite to this bounce")

    # Get existing invites
    existing_result = await db.execute(
        select(BounceInvite.user_id).where(BounceInvite.bounce_id == bounce_id)
    )
    existing_user_ids = {row[0] for row in existing_result.all()}

    # Add new invites
    added = 0
    newly_invited = []
    for user_id in invite_data.user_ids:
        if user_id not in existing_user_ids and user_id != current_user.id:
            invite = BounceInvite(bounce_id=bounce_id, user_id=user_id)
            db.add(invite)
            added += 1
            newly_invited.append(user_id)

    await db.commit()

    logger.info(f"Added {added} invites to bounce {bounce_id}")

    # Queue push notifications to newly invited users (non-blocking)
    for user_id in newly_invited:
        payload = NotificationPayload(
            notification_type=NotificationType.BOUNCE_INVITE,
            title="Bounce Invite",
            body=f"{current_user.nickname or current_user.first_name} invited you to bounce at {bounce.venue_name}",
            actor_id=current_user.id,
            actor_nickname=current_user.nickname or current_user.first_name or "Someone",
            actor_profile_picture=current_user.profile_picture or current_user.instagram_profile_pic,
            bounce_id=bounce.id,
            bounce_venue_name=bounce.venue_name,
            bounce_place_id=bounce.place_id
        )
        enqueue_notification(user_id, payload_to_dict(payload))

    return {"added": added, "total": len(existing_user_ids) + added}


@router.delete("/{bounce_id}/invite/{user_id}")
async def remove_invite(
    bounce_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Remove a user's invite from a bounce.

    Allowed by:
    - The bounce creator (can remove anyone)
    - The invited user themselves (declining the invite)
    """
    result = await db.execute(
        select(Bounce).where(Bounce.id == bounce_id)
    )
    bounce = result.scalar_one_or_none()

    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found")

    is_creator = bounce.creator_id == current_user.id
    is_self = user_id == current_user.id

    if not (is_creator or is_self):
        raise HTTPException(status_code=403, detail="Not authorized to remove this invite")

    # Find and delete the invite
    invite_result = await db.execute(
        select(BounceInvite).where(
            BounceInvite.bounce_id == bounce_id,
            BounceInvite.user_id == user_id
        )
    )
    invite = invite_result.scalar_one_or_none()

    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    await db.delete(invite)
    await db.commit()

    logger.info(f"Invite removed: bounce {bounce_id}, user {user_id}, by {current_user.id}")

    return {"success": True, "message": "Invite removed"}


class InvitedUserInfo(BaseModel):
    user_id: int
    nickname: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    profile_picture: Optional[str]
    invited_at: datetime
    is_checked_in: bool = False


# Constants for check-in status
CHECKIN_EXPIRY_HOURS = 24


@router.get("/{bounce_id}/invites")
async def get_bounce_invites(
    bounce_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get list of users invited to a bounce.
    Includes is_checked_in status if the invited user is currently checked in at the bounce's venue.

    Only accessible by:
    - The bounce creator
    - Users who are invited to the bounce
    - Anyone if the bounce is public
    """
    from db.models import CheckIn

    # Get the bounce
    result = await db.execute(
        select(Bounce).where(Bounce.id == bounce_id)
    )
    bounce = result.scalar_one_or_none()

    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found")

    # Check access
    is_creator = bounce.creator_id == current_user.id

    # Check if user is invited
    invite_check = await db.execute(
        select(BounceInvite).where(
            BounceInvite.bounce_id == bounce_id,
            BounceInvite.user_id == current_user.id
        )
    )
    is_invited = invite_check.scalar_one_or_none() is not None

    if not (bounce.is_public or is_creator or is_invited):
        raise HTTPException(status_code=403, detail="Access denied")

    # Get all invited users
    stmt = (
        select(BounceInvite, User)
        .join(User, BounceInvite.user_id == User.id)
        .where(BounceInvite.bounce_id == bounce_id)
        .order_by(BounceInvite.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Get users checked in at the bounce's venue (if place_id exists)
    checked_in_user_ids = set()
    if bounce.place_id:
        expiry_time = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)
        checkin_result = await db.execute(
            select(CheckIn.user_id).where(
                and_(
                    CheckIn.place_id == bounce.place_id,
                    CheckIn.is_active == True,
                    CheckIn.last_seen_at >= expiry_time
                )
            )
        )
        checked_in_user_ids = {row[0] for row in checkin_result.all()}

    invites = [
        InvitedUserInfo(
            user_id=user.id,
            nickname=user.nickname,
            first_name=user.first_name,
            last_name=user.last_name,
            profile_picture=user.profile_picture or user.instagram_profile_pic,
            invited_at=invite.created_at,
            is_checked_in=user.id in checked_in_user_ids
        )
        for invite, user in rows
    ]

    return {
        "bounce_id": bounce_id,
        "invite_count": len(invites),
        "invites": invites
    }


@router.post("/{bounce_id}/archive", response_model=BounceResponse)
async def archive_bounce(
    bounce_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Archive a bounce (creator only)"""

    result = await db.execute(
        select(Bounce, User)
        .join(User, Bounce.creator_id == User.id)
        .where(Bounce.id == bounce_id)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Bounce not found")

    bounce, user = row

    if bounce.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the creator can archive this bounce")

    bounce.status = 'archived'
    await db.commit()
    await db.refresh(bounce)

    # Get invite count
    count_result = await db.execute(
        select(func.count(BounceInvite.id)).where(BounceInvite.bounce_id == bounce_id)
    )
    invite_count = count_result.scalar() or 0

    return BounceResponse(
        id=bounce.id,
        creator_id=bounce.creator_id,
        creator_nickname=user.nickname,
        creator_profile_pic=user.profile_picture or user.instagram_profile_pic,
        venue_name=bounce.venue_name,
        venue_address=bounce.venue_address,
        latitude=bounce.latitude,
        longitude=bounce.longitude,
        bounce_time=bounce.bounce_time,
        is_now=bounce.is_now,
        is_public=bounce.is_public,
        status=bounce.status,
        invite_count=invite_count,
        created_at=bounce.created_at
    )


# ============== Attendee Tracking ==============
# User can only be checked into ONE bounce at a time.
# When near multiple bounces, client should offer a choice.


class NearbyBounceInfo(BaseModel):
    """Info about a nearby bounce the user can check into"""
    id: int
    venue_name: str
    venue_address: Optional[str]
    latitude: float
    longitude: float
    distance_meters: float
    attendee_count: int
    creator_nickname: Optional[str]


class NearbyBouncesResponse(BaseModel):
    """Response for nearby bounces check"""
    current_checkin: Optional[int] = None  # bounce_id user is currently checked into
    nearby_bounces: List[NearbyBounceInfo]


@router.get("/nearby", response_model=NearbyBouncesResponse)
async def get_nearby_bounces(
    lat: float,
    lng: float,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get public 'now' bounces within check-in proximity.

    Called by client when user enters an area to see available bounces.
    Returns:
    - current_checkin: bounce_id if user is already checked in somewhere
    - nearby_bounces: list of bounces within proximity that user can check into
    """
    # Check if user is already checked into a bounce
    expiry_time = datetime.now(timezone.utc) - timedelta(minutes=ATTENDEE_EXPIRY_MINUTES)
    current_checkin_result = await db.execute(
        select(BounceAttendee.bounce_id)
        .where(
            BounceAttendee.user_id == current_user.id,
            BounceAttendee.last_seen_at >= expiry_time
        )
    )
    current_checkin = current_checkin_result.scalar_one_or_none()

    # Find all active public 'now' bounces
    stmt = (
        select(Bounce, User)
        .join(User, Bounce.creator_id == User.id)
        .where(
            Bounce.is_public == True,
            Bounce.is_now == True,
            Bounce.status == 'active'
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    nearby = []
    for bounce, creator in rows:
        distance_km = haversine_distance(lat, lng, bounce.latitude, bounce.longitude)
        if distance_km <= BOUNCE_PROXIMITY_KM:
            # Get attendee count
            attendee_count, _ = await get_active_attendees(db, bounce.id, include_details=False)

            nearby.append(NearbyBounceInfo(
                id=bounce.id,
                venue_name=bounce.venue_name,
                venue_address=bounce.venue_address,
                latitude=bounce.latitude,
                longitude=bounce.longitude,
                distance_meters=distance_km * 1000,
                attendee_count=attendee_count,
                creator_nickname=creator.nickname
            ))

    # Sort by distance
    nearby.sort(key=lambda b: b.distance_meters)

    return NearbyBouncesResponse(
        current_checkin=current_checkin,
        nearby_bounces=nearby
    )


@router.post("/{bounce_id}/checkin")
async def checkin_to_bounce(
    bounce_id: int,
    lat: float,
    lng: float,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Check in to a public 'now' bounce.

    User must be within 100m of the bounce location.
    User can only be checked into ONE bounce at a time - checking into a new
    bounce will automatically check them out of any previous bounce.
    """
    # Get the bounce
    result = await db.execute(
        select(Bounce).where(Bounce.id == bounce_id)
    )
    bounce = result.scalar_one_or_none()

    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found")

    # For private bounces, only creator and invited users can check in
    if not bounce.is_public and bounce.creator_id != current_user.id:
        # Check if user is invited
        invite_check = await db.execute(
            select(BounceInvite).where(
                BounceInvite.bounce_id == bounce_id,
                BounceInvite.user_id == current_user.id
            )
        )
        if not invite_check.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Can only check in to public bounces or bounces you're invited to")

    if not bounce.is_now:
        raise HTTPException(status_code=400, detail="Can only check in to 'now' bounces")

    if bounce.status != 'active':
        raise HTTPException(status_code=400, detail="Bounce is not active")

    # Check proximity
    distance = haversine_distance(lat, lng, bounce.latitude, bounce.longitude)
    if distance > BOUNCE_PROXIMITY_KM:
        raise HTTPException(
            status_code=400,
            detail=f"Too far from bounce location. You are {distance*1000:.0f}m away, must be within {BOUNCE_PROXIMITY_KM*1000:.0f}m"
        )

    now = datetime.now(timezone.utc)
    previous_bounce_id = None

    # Check if user is already checked into ANY bounce (not just this one)
    existing_checkins = await db.execute(
        select(BounceAttendee)
        .where(BounceAttendee.user_id == current_user.id)
    )
    existing_attendees = existing_checkins.scalars().all()

    # Remove user from any other bounces
    for attendee in existing_attendees:
        if attendee.bounce_id != bounce_id:
            previous_bounce_id = attendee.bounce_id
            await db.delete(attendee)
            logger.info(f"User {current_user.id} auto-checked out of bounce {attendee.bounce_id}")

    # Check if already at this bounce
    current_attendee = next(
        (a for a in existing_attendees if a.bounce_id == bounce_id),
        None
    )

    if current_attendee:
        # Update last seen time
        current_attendee.last_seen_at = now
    else:
        # Create new attendance record
        attendee = BounceAttendee(
            bounce_id=bounce_id,
            user_id=current_user.id,
            joined_at=now,
            last_seen_at=now
        )
        db.add(attendee)

    await db.commit()

    # Broadcast update for previous bounce if user switched
    if previous_bounce_id:
        prev_count, prev_attendees = await get_active_attendees(db, previous_bounce_id, include_details=True)
        await manager.broadcast({
            "type": "bounce_attendee_update",
            "bounce_id": previous_bounce_id,
            "attendee_count": prev_count,
            "attendees": [a.model_dump(mode='json') for a in prev_attendees]
        })

    # Get updated attendee count for current bounce
    count, attendees = await get_active_attendees(db, bounce_id, include_details=True)

    logger.info(f"User {current_user.id} checked in to bounce {bounce_id}. Total attendees: {count}")

    # Broadcast attendee update via WebSocket
    await manager.broadcast({
        "type": "bounce_attendee_update",
        "bounce_id": bounce_id,
        "attendee_count": count,
        "attendees": [a.model_dump(mode='json') for a in attendees]
    })

    return {
        "success": True,
        "bounce_id": bounce_id,
        "attendee_count": count,
        "attendees": attendees,
        "previous_bounce_id": previous_bounce_id  # Let client know if they were auto-checked out
    }


@router.post("/{bounce_id}/leave")
async def leave_bounce(
    bounce_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Leave a bounce (remove attendance record).
    """
    result = await db.execute(
        select(BounceAttendee).where(
            BounceAttendee.bounce_id == bounce_id,
            BounceAttendee.user_id == current_user.id
        )
    )
    attendee = result.scalar_one_or_none()

    if not attendee:
        raise HTTPException(status_code=404, detail="Not checked in to this bounce")

    await db.delete(attendee)
    await db.commit()

    # Get updated attendee count
    count, attendees = await get_active_attendees(db, bounce_id, include_details=True)

    logger.info(f"User {current_user.id} left bounce {bounce_id}. Total attendees: {count}")

    # Broadcast attendee update
    await manager.broadcast({
        "type": "bounce_attendee_update",
        "bounce_id": bounce_id,
        "attendee_count": count,
        "attendees": [a.model_dump(mode='json') for a in attendees]
    })

    return {"success": True, "bounce_id": bounce_id}


@router.get("/my-checkin")
async def get_my_checkin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get the bounce the current user is checked into (if any).
    """
    expiry_time = datetime.now(timezone.utc) - timedelta(minutes=ATTENDEE_EXPIRY_MINUTES)

    result = await db.execute(
        select(BounceAttendee, Bounce, User)
        .join(Bounce, BounceAttendee.bounce_id == Bounce.id)
        .join(User, Bounce.creator_id == User.id)
        .where(
            BounceAttendee.user_id == current_user.id,
            BounceAttendee.last_seen_at >= expiry_time
        )
    )
    row = result.first()

    if not row:
        return {"checked_in": False, "bounce": None}

    attendee, bounce, creator = row
    count, _ = await get_active_attendees(db, bounce.id, include_details=False)

    return {
        "checked_in": True,
        "bounce": {
            "id": bounce.id,
            "venue_name": bounce.venue_name,
            "venue_address": bounce.venue_address,
            "latitude": bounce.latitude,
            "longitude": bounce.longitude,
            "creator_nickname": creator.nickname,
            "attendee_count": count,
            "checked_in_at": attendee.joined_at,
            "last_seen_at": attendee.last_seen_at
        }
    }


@router.get("/{bounce_id}/attendees")
async def get_bounce_attendees(
    bounce_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get list of current attendees at a public now bounce.
    """
    # Check bounce exists and is public
    result = await db.execute(
        select(Bounce).where(Bounce.id == bounce_id)
    )
    bounce = result.scalar_one_or_none()

    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found")

    if not bounce.is_public:
        raise HTTPException(status_code=403, detail="Attendee list only available for public bounces")

    count, attendees = await get_active_attendees(db, bounce_id, include_details=True)

    return {
        "bounce_id": bounce_id,
        "attendee_count": count,
        "attendees": attendees
    }
