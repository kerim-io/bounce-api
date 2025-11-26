from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import logging

from db.database import get_async_session
from db.models import Bounce, BounceInvite, User
from api.dependencies import get_current_user
from services.geofence import haversine_distance

router = APIRouter(prefix="/bounces", tags=["bounces"])
logger = logging.getLogger(__name__)


# Request/Response Schemas
class BounceCreate(BaseModel):
    venue_name: str
    venue_address: Optional[str] = None
    latitude: float
    longitude: float
    bounce_time: datetime
    is_now: bool = False
    is_public: bool = False
    invite_user_ids: Optional[List[int]] = None


class BounceResponse(BaseModel):
    id: int
    creator_id: int
    creator_nickname: Optional[str]
    creator_profile_pic: Optional[str]
    venue_name: str
    venue_address: Optional[str]
    latitude: float
    longitude: float
    bounce_time: datetime
    is_now: bool
    is_public: bool
    status: str
    invite_count: int
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
        # Create the bounce
        bounce = Bounce(
            creator_id=current_user.id,
            venue_name=bounce_data.venue_name,
            venue_address=bounce_data.venue_address,
            latitude=bounce_data.latitude,
            longitude=bounce_data.longitude,
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

        return BounceResponse(
            id=bounce.id,
            creator_id=bounce.creator_id,
            creator_nickname=current_user.nickname,
            creator_profile_pic=current_user.profile_picture,
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
            creator_profile_pic=user.profile_picture,
            venue_name=bounce.venue_name,
            venue_address=bounce.venue_address,
            latitude=bounce.latitude,
            longitude=bounce.longitude,
            bounce_time=bounce.bounce_time,
            is_now=bounce.is_now,
            is_public=bounce.is_public,
            status=bounce.status,
            invite_count=invite_count or 0,
            created_at=bounce.created_at
        )
        for bounce, user, invite_count in rows
    ]


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
            creator_profile_pic=user.profile_picture,
            venue_name=bounce.venue_name,
            venue_address=bounce.venue_address,
            latitude=bounce.latitude,
            longitude=bounce.longitude,
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
            creator_profile_pic=user.profile_picture,
            venue_name=bounce.venue_name,
            venue_address=bounce.venue_address,
            latitude=bounce.latitude,
            longitude=bounce.longitude,
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
                    creator_profile_pic=user.profile_picture,
                    venue_name=bounce.venue_name,
                    venue_address=bounce.venue_address,
                    latitude=bounce.latitude,
                    longitude=bounce.longitude,
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
        creator_profile_pic=user.profile_picture,
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
    for user_id in invite_data.user_ids:
        if user_id not in existing_user_ids and user_id != current_user.id:
            invite = BounceInvite(bounce_id=bounce_id, user_id=user_id)
            db.add(invite)
            added += 1

    await db.commit()

    logger.info(f"Added {added} invites to bounce {bounce_id}")

    return {"added": added, "total": len(existing_user_ids) + added}


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
        creator_profile_pic=user.profile_picture,
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
