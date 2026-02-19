from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_, func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from math import radians, sin, cos, sqrt, atan2

from db.database import get_async_session
from db.models import CheckIn, CheckInHistory, User, Place, Bounce, Follow
from api.dependencies import get_current_user
from services.geofence import is_in_basel_area
from services.places.service import get_place_with_photos
from api.routes.websocket import manager
from services.apns_service import NotificationPayload, NotificationType
from services.cache import cache_get, cache_set, cache_delete
from services.tasks import enqueue_notification, payload_to_dict
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checkins", tags=["checkins"])

# Constants
CHECKIN_PROXIMITY_METERS = 20  # Must be within 20m to check in
CHECKIN_EXPIRY_HOURS = 24  # Check-ins expire after 24 hours of inactivity
AUTO_CHECKOUT_RADIUS_METERS = 150  # Auto-checkout when user is >150m from venue (hysteresis)


async def move_checkin_to_history(db: AsyncSession, checkin: CheckIn) -> None:
    """Move a check-in to history table and delete from active check-ins."""
    # Create history record
    history = CheckInHistory(
        user_id=checkin.user_id,
        place_id=checkin.place_id,
        places_fk_id=checkin.places_fk_id,
        venue_name=checkin.location_name,
        venue_address=None,
        latitude=checkin.latitude,
        longitude=checkin.longitude,
        checked_in_at=checkin.created_at,
        checked_out_at=datetime.now(timezone.utc)
    )
    db.add(history)
    # Delete from active check-ins
    await db.delete(checkin)


async def auto_checkout_if_needed(db: AsyncSession, user_id: int, user_lat: float, user_lng: float) -> Optional[str]:
    """
    Check if user has an active venue check-in and is far enough away to auto-checkout.
    Returns the place_id if auto-checkout was performed, None otherwise.
    """
    expiry_time = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)
    result = await db.execute(
        select(CheckIn).where(
            and_(
                CheckIn.user_id == user_id,
                CheckIn.is_active == True,
                CheckIn.last_seen_at >= expiry_time,
                CheckIn.places_fk_id.isnot(None)
            )
        )
    )
    checkin = result.scalar_one_or_none()
    if not checkin:
        return None

    # Get venue coordinates from the Place record
    place_result = await db.execute(
        select(Place).where(Place.id == checkin.places_fk_id)
    )
    place = place_result.scalar_one_or_none()
    if not place:
        return None

    distance = haversine_distance(user_lat, user_lng, place.latitude, place.longitude)
    if distance <= AUTO_CHECKOUT_RADIUS_METERS:
        return None

    place_id = checkin.place_id
    venue_name = checkin.location_name

    # Auto-checkout: move to history
    await move_checkin_to_history(db, checkin)
    await db.commit()

    # Invalidate venue count cache
    if place_id:
        await cache_delete(f"venue_count:{place_id}")

    # Broadcast checkout to all connected clients
    await manager.broadcast({
        "type": "venue_checkout",
        "place_id": place_id,
        "venue_name": venue_name,
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    logger.info(f"Auto-checkout user {user_id} from venue {place_id} (distance: {int(distance)}m)")
    return place_id


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance between two points in meters using Haversine formula."""
    R = 6371000  # Earth's radius in meters
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lng2 - lng1)

    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


class CheckInCreate(BaseModel):
    latitude: float
    longitude: float
    location_name: str


class CheckInResponse(BaseModel):
    id: int
    user_id: int
    username: Optional[str]
    latitude: float
    longitude: float
    location_name: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/", response_model=CheckInResponse)
async def create_checkin(
    checkin_data: CheckInCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Check in at Art Basel location"""
    # Verify location is in Basel area
    if not is_in_basel_area(checkin_data.latitude, checkin_data.longitude):
        raise HTTPException(
            status_code=400,
            detail="Location must be within Art Basel Miami area"
        )

    checkin = CheckIn(
        user_id=current_user.id,
        latitude=checkin_data.latitude,
        longitude=checkin_data.longitude,
        location_name=checkin_data.location_name
    )
    db.add(checkin)
    await db.commit()
    await db.refresh(checkin)

    return CheckInResponse(
        id=checkin.id,
        user_id=checkin.user_id,
        username=current_user.username,
        latitude=checkin.latitude,
        longitude=checkin.longitude,
        location_name=checkin.location_name,
        created_at=checkin.created_at
    )


@router.get("/recent", response_model=List[CheckInResponse])
async def get_recent_checkins(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get recent check-ins"""
    result = await db.execute(
        select(CheckIn, User)
        .join(User, CheckIn.user_id == User.id)
        .order_by(desc(CheckIn.created_at))
        .limit(limit)
    )

    checkins_data = result.all()

    return [
        CheckInResponse(
            id=checkin.id,
            user_id=checkin.user_id,
            username=user.username,
            latitude=checkin.latitude,
            longitude=checkin.longitude,
            location_name=checkin.location_name,
            created_at=checkin.created_at
        )
        for checkin, user in checkins_data
    ]


# ============================================================================
# VENUE CHECK-IN ENDPOINTS
# ============================================================================

class VenueCheckInCreate(BaseModel):
    """Request body for venue check-in"""
    latitude: float  # User's current location
    longitude: float
    venue_name: str
    venue_address: Optional[str] = None
    venue_lat: float  # Venue's location
    venue_lng: float


class VenueCheckInResponse(BaseModel):
    id: int
    user_id: int
    place_id: str
    venue_name: Optional[str]
    checked_in_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


class VenueCheckInCountResponse(BaseModel):
    place_id: str
    count: int


class VenueAttendeeResponse(BaseModel):
    user_id: int
    nickname: Optional[str]
    profile_picture: Optional[str]
    checked_in_at: datetime

    class Config:
        from_attributes = True


class VenueAttendeesResponse(BaseModel):
    place_id: str
    count: int
    attendees: List[VenueAttendeeResponse]
    can_see_details: bool  # True if user is part of a bounce at this venue


class VenueWithCheckInsResponse(BaseModel):
    place_id: str
    name: str
    address: Optional[str]
    latitude: float
    longitude: float
    checkin_count: int
    photos: List[dict] = []


class VenuesWithCheckInsResponse(BaseModel):
    venues: List[VenueWithCheckInsResponse]
    total_checked_in_users: int


@router.get("/area", response_model=VenuesWithCheckInsResponse)
async def get_venues_with_checkins_in_area(
    lat: float,
    lng: float,
    radius: float = 5000,
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get all venues with active check-ins within a radius.
    Returns venues with their check-in counts for map display.
    """
    from db.models import GooglePic

    expiry_time = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)

    # Get all active check-ins grouped by place_id
    # Note: latitude/longitude in CheckIn are USER locations, not venue locations
    # So we only group by place_id and get venue coords from Place table
    result = await db.execute(
        select(
            CheckIn.place_id,
            func.count(CheckIn.id).label('checkin_count')
        )
        .where(
            and_(
                CheckIn.is_active == True,
                CheckIn.last_seen_at >= expiry_time,
                CheckIn.place_id.isnot(None)
            )
        )
        .group_by(CheckIn.place_id)
    )

    venues = []
    rows = result.all()
    for row in rows:
        # Get place info from Place table (required for accurate coordinates)
        place_result = await db.execute(
            select(Place).where(Place.place_id == row.place_id)
        )
        place = place_result.scalar_one_or_none()

        if not place:
            continue

        # Filter by distance using venue coordinates from Place table
        distance = haversine_distance(lat, lng, place.latitude, place.longitude)
        if distance <= radius:
            # Get photos
            photos = []
            pics_result = await db.execute(
                select(GooglePic).where(GooglePic.place_id == place.id).limit(3)
            )
            for pic in pics_result.scalars().all():
                photos.append({"url": pic.photo_url or pic.photo_reference})

            venues.append(VenueWithCheckInsResponse(
                place_id=row.place_id,
                name=place.name,
                address=place.address,
                latitude=place.latitude,
                longitude=place.longitude,
                checkin_count=row.checkin_count,
                photos=photos
            ))

    total_users = sum(v.checkin_count for v in venues)
    return VenuesWithCheckInsResponse(venues=venues, total_checked_in_users=total_users)


@router.post("/venue/{place_id}", response_model=VenueCheckInResponse)
async def checkin_to_venue(
    place_id: str,
    checkin_data: VenueCheckInCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Check in to a venue by Place ID.
    User must be within 100m of the venue location.
    """
    # Get or create the Place record
    place = await get_place_with_photos(
        db=db,
        place_id=place_id,
        venue_name=checkin_data.venue_name,
        venue_address=checkin_data.venue_address,
        latitude=checkin_data.venue_lat,
        longitude=checkin_data.venue_lng,
        source="checkin"
    )

    if not place:
        raise HTTPException(status_code=404, detail="Place not found")

    # Verify user is within proximity
    distance = haversine_distance(
        checkin_data.latitude, checkin_data.longitude,
        place.latitude, place.longitude
    )
    if distance > CHECKIN_PROXIMITY_METERS:
        raise HTTPException(
            status_code=400,
            detail=f"You must be within {CHECKIN_PROXIMITY_METERS}m of the venue to check in. You are {int(distance)}m away."
        )

    # Check for existing active check-in at this venue
    expiry_time = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)
    existing_checkin = await db.execute(
        select(CheckIn).where(
            and_(
                CheckIn.user_id == current_user.id,
                CheckIn.place_id == place_id,
                CheckIn.is_active == True,
                CheckIn.last_seen_at >= expiry_time
            )
        )
    )
    existing = existing_checkin.scalar_one_or_none()

    if existing:
        # Update last_seen_at to refresh the check-in
        existing.last_seen_at = datetime.now(timezone.utc)
        existing.latitude = checkin_data.latitude
        existing.longitude = checkin_data.longitude
        await db.commit()
        await db.refresh(existing)

        return VenueCheckInResponse(
            id=existing.id,
            user_id=existing.user_id,
            place_id=place_id,
            venue_name=place.name,
            checked_in_at=existing.created_at,
            is_active=existing.is_active
        )

    # Move any other active check-ins for this user to history (user can only be at one place)
    result = await db.execute(
        select(CheckIn).where(
            and_(
                CheckIn.user_id == current_user.id,
                CheckIn.is_active == True
            )
        )
    )
    old_place_ids = []
    for old_checkin in result.scalars().all():
        if old_checkin.place_id:
            old_place_ids.append(old_checkin.place_id)
        # Move to history and delete
        await move_checkin_to_history(db, old_checkin)

    # Invalidate cache for old venues
    for old_place_id in old_place_ids:
        await cache_delete(f"venue_count:{old_place_id}")

    # Create new check-in
    checkin = CheckIn(
        user_id=current_user.id,
        latitude=checkin_data.latitude,
        longitude=checkin_data.longitude,
        location_name=place.name,
        place_id=place_id,
        places_fk_id=place.id,
        last_seen_at=datetime.now(timezone.utc),
        is_active=True
    )
    db.add(checkin)
    await db.commit()
    await db.refresh(checkin)

    # Invalidate venue count cache
    await cache_delete(f"venue_count:{place_id}")

    # Broadcast check-in to all connected clients
    await manager.broadcast({
        "type": "venue_checkin",
        "place_id": place_id,
        "venue_name": place.name,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "user_id": current_user.id,
        "nickname": current_user.nickname,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    # Send notifications to users at the same venue who follow the current user
    expiry_time = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)

    # Get users who are checked into the same venue AND follow the current user
    same_venue_followers_result = await db.execute(
        select(User, CheckIn).join(
            CheckIn, CheckIn.user_id == User.id
        ).join(
            Follow, and_(
                Follow.follower_id == User.id,
                Follow.following_id == current_user.id
            )
        ).where(
            and_(
                CheckIn.place_id == place_id,
                CheckIn.is_active == True,
                CheckIn.last_seen_at >= expiry_time,
                User.id != current_user.id
            )
        )
    )

    # Send notifications (WebSocket + push)
    from services.tasks import send_websocket_notification

    # Notify users at the same venue
    for user, _ in same_venue_followers_result.all():
        payload = NotificationPayload(
            notification_type=NotificationType.FRIEND_AT_VENUE,
            title="Friend Arrived",
            body=f"{current_user.nickname} just arrived at {place.name}",
            actor_id=current_user.id,
            actor_nickname=current_user.nickname or current_user.first_name or "Someone",
            actor_profile_picture=current_user.profile_picture or current_user.instagram_profile_pic,
            venue_place_id=place_id,
            venue_name=place.name,
            venue_latitude=place.latitude,
            venue_longitude=place.longitude
        )
        payload_dict = payload_to_dict(payload)
        await send_websocket_notification(user.id, payload_dict)
        enqueue_notification(user.id, payload_dict)
        logger.info(f"Sent friend_at_venue notification for user {user.id}")

    # Notify users who have the current user marked as a close friend
    close_friend_followers_result = await db.execute(
        select(User).join(
            Follow, and_(
                Follow.follower_id == User.id,
                Follow.following_id == current_user.id,
                Follow.is_close_friend == True
            )
        ).where(User.id != current_user.id)
    )

    for user in close_friend_followers_result.scalars().all():
        payload = NotificationPayload(
            notification_type=NotificationType.CLOSE_FRIEND_CHECKIN,
            title="Close Friend Check-in",
            body=f"{current_user.nickname} checked into {place.name}",
            actor_id=current_user.id,
            actor_nickname=current_user.nickname or current_user.first_name or "Someone",
            actor_profile_picture=current_user.profile_picture or current_user.instagram_profile_pic,
            venue_place_id=place_id,
            venue_name=place.name,
            venue_latitude=place.latitude,
            venue_longitude=place.longitude
        )
        payload_dict = payload_to_dict(payload)
        await send_websocket_notification(user.id, payload_dict)
        enqueue_notification(user.id, payload_dict)
        logger.info(f"Sent close_friend_checkin notification for user {user.id}")

    return VenueCheckInResponse(
        id=checkin.id,
        user_id=checkin.user_id,
        place_id=place_id,
        venue_name=place.name,
        checked_in_at=checkin.created_at,
        is_active=checkin.is_active
    )


@router.get("/venue/{place_id}/count", response_model=VenueCheckInCountResponse)
async def get_venue_checkin_count(
    place_id: str,
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get count of people checked in at venue (public, no auth required).
    """
    cache_key = f"venue_count:{place_id}"
    cached_count = await cache_get(cache_key)

    if cached_count is not None:
        return VenueCheckInCountResponse(
            place_id=place_id,
            count=cached_count
        )

    expiry_time = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)

    result = await db.execute(
        select(func.count(CheckIn.id)).where(
            and_(
                CheckIn.place_id == place_id,
                CheckIn.is_active == True,
                CheckIn.last_seen_at >= expiry_time
            )
        )
    )
    count = result.scalar() or 0

    # Cache for 2 minutes
    await cache_set(cache_key, count, ttl=120)

    return VenueCheckInCountResponse(
        place_id=place_id,
        count=count
    )


@router.get("/venue/{place_id}/attendees", response_model=VenueAttendeesResponse)
async def get_venue_attendees(
    place_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get list of people checked in at venue.
    Returns attendee details only if user is part of an active bounce at this venue.
    Otherwise, returns just the count.
    """
    expiry_time = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)

    # Get count of active check-ins
    count_result = await db.execute(
        select(func.count(CheckIn.id)).where(
            and_(
                CheckIn.place_id == place_id,
                CheckIn.is_active == True,
                CheckIn.last_seen_at >= expiry_time
            )
        )
    )
    count = count_result.scalar() or 0

    # Any authenticated user can see who's checked in at a venue
    can_see_details = True

    attendees = []
    if can_see_details:
        # Get attendee details
        result = await db.execute(
            select(CheckIn, User)
            .join(User, CheckIn.user_id == User.id)
            .where(
                and_(
                    CheckIn.place_id == place_id,
                    CheckIn.is_active == True,
                    CheckIn.last_seen_at >= expiry_time
                )
            )
            .order_by(desc(CheckIn.last_seen_at))
        )

        for checkin, user in result.all():
            attendees.append(VenueAttendeeResponse(
                user_id=user.id,
                nickname=user.nickname or user.username,
                profile_picture=user.profile_picture or user.instagram_profile_pic,
                checked_in_at=checkin.created_at
            ))

    return VenueAttendeesResponse(
        place_id=place_id,
        count=count,
        attendees=attendees,
        can_see_details=can_see_details
    )


@router.delete("/venue/{place_id}")
async def checkout_from_venue(
    place_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Check out from a venue (deactivate check-in).
    """
    result = await db.execute(
        select(CheckIn).where(
            and_(
                CheckIn.user_id == current_user.id,
                CheckIn.place_id == place_id,
                CheckIn.is_active == True
            )
        )
    )
    checkin = result.scalar_one_or_none()

    if not checkin:
        raise HTTPException(status_code=404, detail="No active check-in found at this venue")

    # Get venue name before moving to history
    place_result = await db.execute(
        select(Place).where(Place.place_id == place_id)
    )
    place = place_result.scalar_one_or_none()
    venue_name = place.name if place else checkin.location_name

    # Move to history and delete from active check-ins
    await move_checkin_to_history(db, checkin)
    await db.commit()

    # Invalidate venue count cache
    await cache_delete(f"venue_count:{place_id}")

    # Notify users at the same venue who follow the current user
    expiry_time = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)

    same_venue_followers_result = await db.execute(
        select(User, CheckIn).join(
            CheckIn, CheckIn.user_id == User.id
        ).join(
            Follow, and_(
                Follow.follower_id == User.id,
                Follow.following_id == current_user.id
            )
        ).where(
            and_(
                CheckIn.place_id == place_id,
                CheckIn.is_active == True,
                CheckIn.last_seen_at >= expiry_time,
                User.id != current_user.id
            )
        )
    )

    # Send notifications (WebSocket + push)
    from services.tasks import send_websocket_notification

    for user, _ in same_venue_followers_result.all():
        payload = NotificationPayload(
            notification_type=NotificationType.FRIEND_LEFT_VENUE,
            title="Friend Left",
            body=f"{current_user.nickname} left {venue_name}",
            actor_id=current_user.id,
            actor_nickname=current_user.nickname or current_user.first_name or "Someone",
            actor_profile_picture=current_user.profile_picture or current_user.instagram_profile_pic,
            venue_place_id=place_id,
            venue_name=venue_name,
            venue_latitude=place.latitude if place else None,
            venue_longitude=place.longitude if place else None
        )
        payload_dict = payload_to_dict(payload)
        await send_websocket_notification(user.id, payload_dict)
        enqueue_notification(user.id, payload_dict)
        logger.info(f"Sent friend_left_venue notification for user {user.id}")

    # Broadcast checkout to all connected clients
    await manager.broadcast({
        "type": "venue_checkout",
        "place_id": place_id,
        "venue_name": venue_name,
        "user_id": current_user.id,
        "nickname": current_user.nickname,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    return {"message": "Successfully checked out"}


# ============================================================================
# CHECK-IN HISTORY ENDPOINTS
# ============================================================================

class CheckInHistoryResponse(BaseModel):
    id: int
    user_id: int
    place_id: str
    venue_name: str
    venue_address: Optional[str]
    latitude: float
    longitude: float
    checked_in_at: datetime
    checked_out_at: Optional[datetime]

    class Config:
        from_attributes = True


class CheckInHistoryWithUser(CheckInHistoryResponse):
    nickname: Optional[str]
    profile_picture: Optional[str]


@router.get("/history/me", response_model=List[CheckInHistoryResponse])
async def get_my_checkin_history(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get current user's check-in history."""
    result = await db.execute(
        select(CheckInHistory)
        .where(CheckInHistory.user_id == current_user.id)
        .order_by(desc(CheckInHistory.checked_in_at))
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.get("/history/user/{user_id}", response_model=List[CheckInHistoryResponse])
async def get_user_checkin_history(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get a user's check-in history."""
    result = await db.execute(
        select(CheckInHistory)
        .where(CheckInHistory.user_id == user_id)
        .order_by(desc(CheckInHistory.checked_in_at))
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.get("/history/venue/{place_id}", response_model=List[CheckInHistoryWithUser])
async def get_venue_checkin_history(
    place_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get a venue's check-in history (all users who checked in)."""
    result = await db.execute(
        select(CheckInHistory, User)
        .join(User, CheckInHistory.user_id == User.id)
        .where(CheckInHistory.place_id == place_id)
        .order_by(desc(CheckInHistory.checked_in_at))
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()

    return [
        CheckInHistoryWithUser(
            id=checkin.id,
            user_id=checkin.user_id,
            place_id=checkin.place_id,
            venue_name=checkin.venue_name,
            venue_address=checkin.venue_address,
            latitude=checkin.latitude,
            longitude=checkin.longitude,
            checked_in_at=checkin.checked_in_at,
            checked_out_at=checkin.checked_out_at,
            nickname=user.nickname,
            profile_picture=user.profile_picture or user.instagram_profile_pic
        )
        for checkin, user in rows
    ]
