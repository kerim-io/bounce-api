from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from typing import Optional, List
import aiofiles
from pathlib import Path
import uuid
import os
import hashlib
from datetime import datetime
from math import radians, cos, sin, asin, sqrt

from db.database import get_async_session
from db.models import User, Follow, Post, Like, CheckIn, RefreshToken
from api.dependencies import get_current_user
from core.config import settings

router = APIRouter(prefix="/users", tags=["users"])


class ProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    nickname: Optional[str] = None
    employer: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    profile_picture_url: Optional[str] = None
    # Privacy settings for Art Basel Miami access control
    phone_visible: Optional[bool] = None
    email_visible: Optional[bool] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    bio: Optional[str] = None
    profile_picture: Optional[str] = None


class ProfileResponse(BaseModel):
    id: int
    first_name: Optional[str]
    last_name: Optional[str]
    nickname: Optional[str]
    employer: Optional[str]
    phone: Optional[str] = None
    email: Optional[str] = None
    profile_picture: Optional[str]
    has_profile: bool
    # Privacy flags (only shown to owner)
    phone_visible: Optional[bool] = None
    email_visible: Optional[bool] = None

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    id: int
    username: Optional[str]
    bio: Optional[str]
    profile_picture: Optional[str]
    email: Optional[str]

    class Config:
        from_attributes = True


class SimpleUserResponse(BaseModel):
    """Simple user info for follow lists"""
    id: int
    nickname: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    profile_picture: Optional[str]
    employer: Optional[str]

    class Config:
        from_attributes = True


class LocationUpdate(BaseModel):
    """Update user location for Art Basel Miami geofence check"""
    latitude: float
    longitude: float


class LocationResponse(BaseModel):
    """Response after location update"""
    can_post: bool
    message: str
    distance_km: Optional[float] = None


class DeleteAccountResponse(BaseModel):
    """Response after account deletion"""
    success: bool
    message: str
    deleted_data: dict


class QRTokenResponse(BaseModel):
    """Response containing user's QR token"""
    qr_token: str


class QRConnectRequest(BaseModel):
    """Request to connect via QR code"""
    qr_token: str


class QRConnectResponse(BaseModel):
    """Response after QR code connection"""
    success: bool
    message: str
    connected_user: SimpleUserResponse


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Get current user profile"""
    return current_user


@router.get("/me/profile", response_model=ProfileResponse)
async def get_profile(current_user: User = Depends(get_current_user)):
    """Get current user full profile"""
    return ProfileResponse(
        id=current_user.id,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        nickname=current_user.nickname,
        employer=current_user.employer,
        phone=current_user.phone,
        email=current_user.email,
        profile_picture=current_user.profile_picture,
        has_profile=current_user.has_profile
    )


@router.put("/me/profile", response_model=ProfileResponse)
async def update_profile_full(
    profile_data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Update current user profile with privacy settings for Art Basel Miami"""
    if profile_data.first_name is not None:
        current_user.first_name = profile_data.first_name
    if profile_data.last_name is not None:
        current_user.last_name = profile_data.last_name
    if profile_data.nickname is not None:
        current_user.nickname = profile_data.nickname
    if profile_data.employer is not None:
        current_user.employer = profile_data.employer
    if profile_data.phone is not None:
        current_user.phone = profile_data.phone
    if profile_data.email is not None:
        current_user.email = profile_data.email
    if profile_data.profile_picture_url is not None:
        current_user.profile_picture = profile_data.profile_picture_url

    # Privacy settings
    if profile_data.phone_visible is not None:
        current_user.phone_visible = profile_data.phone_visible
    if profile_data.email_visible is not None:
        current_user.email_visible = profile_data.email_visible

    await db.commit()
    await db.refresh(current_user)

    return ProfileResponse(
        id=current_user.id,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        nickname=current_user.nickname,
        employer=current_user.employer,
        phone=current_user.phone,
        email=current_user.email,
        profile_picture=current_user.profile_picture,
        has_profile=current_user.has_profile,
        phone_visible=current_user.phone_visible,
        email_visible=current_user.email_visible
    )


@router.post("/me/profile-picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Upload profile picture (multipart/form-data)"""
    # Validate file type
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only JPEG, PNG, WEBP allowed")

    # Generate unique filename
    ext = file.filename.split(".")[-1]
    filename = f"profile_{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"

    # Save to uploads directory
    upload_dir = Path(settings.UPLOAD_DIR) / "profile_pictures"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename

    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # Update user profile picture URL
    profile_picture_url = f"/files/profile_pictures/{filename}"
    current_user.profile_picture = profile_picture_url
    await db.commit()

    return {
        "success": True,
        "profile_picture_url": profile_picture_url
    }


@router.put("/me", response_model=UserResponse)
async def update_profile(
    update_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Update current user profile (legacy)"""
    if update_data.username:
        current_user.username = update_data.username
    if update_data.bio:
        current_user.bio = update_data.bio
    if update_data.profile_picture:
        current_user.profile_picture = update_data.profile_picture

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/follow/{user_id}")
async def follow_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Follow a user"""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    # Check if already following
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail="Already following")

    follow = Follow(follower_id=current_user.id, following_id=user_id)
    db.add(follow)
    await db.commit()

    return {"status": "success"}


@router.delete("/follow/{user_id}")
async def unfollow_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Unfollow a user"""
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = result.scalar_one_or_none()

    if not follow:
        raise HTTPException(status_code=404, detail="Not following this user")

    await db.delete(follow)
    await db.commit()

    return {"status": "success"}


@router.get("/me/following", response_model=List[SimpleUserResponse])
async def get_following(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get list of users current user is following"""
    result = await db.execute(
        select(User).join(
            Follow, Follow.following_id == User.id
        ).where(Follow.follower_id == current_user.id)
    )
    users = result.scalars().all()
    return users


@router.get("/me/followers", response_model=List[SimpleUserResponse])
async def get_followers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get list of users following current user"""
    result = await db.execute(
        select(User).join(
            Follow, Follow.follower_id == User.id
        ).where(Follow.following_id == current_user.id)
    )
    users = result.scalars().all()
    return users


@router.get("/{user_id}/profile", response_model=ProfileResponse)
async def get_user_profile(
    user_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get another user's profile with privacy controls.

    Phone/email only visible if:
    - User has made them visible (phone_visible/email_visible = True) AND
    - Requesting user is geolocated at Art Basel Miami (can_post = True)
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Conditional privacy: only show phone/email to geolocated users
    can_see_private = current_user.can_post  # Geolocated at Art Basel Miami

    return ProfileResponse(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        nickname=user.nickname,
        employer=user.employer,
        phone=user.phone if (user.phone_visible and can_see_private) else None,
        email=user.email if (user.email_visible and can_see_private) else None,
        profile_picture=user.profile_picture,
        has_profile=user.has_profile,
        phone_visible=None,  # Privacy flags not shown to others
        email_visible=None
    )


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance in kilometers between two points
    on the earth (specified in decimal degrees)
    """
    # Convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    r = 6371  # Radius of earth in kilometers
    return c * r


@router.post("/me/location", response_model=LocationResponse)
async def update_location(
    location: LocationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Update user location and check if they're at Art Basel Miami.

    Users within the geofence can post and like.
    Returns can_post status based on distance from Basel coordinates.
    """
    # Art Basel Miami coordinates (from .env)
    basel_lat = settings.BASEL_LAT
    basel_lon = settings.BASEL_LON
    basel_radius_km = settings.BASEL_RADIUS_KM

    # Calculate distance from Art Basel venue
    distance_km = haversine_distance(
        location.latitude,
        location.longitude,
        basel_lat,
        basel_lon
    )

    # Update user location
    current_user.last_location_lat = location.latitude
    current_user.last_location_lon = location.longitude
    current_user.last_location_update = datetime.utcnow()

    # Check if within geofence
    can_post = distance_km <= basel_radius_km
    current_user.can_post = can_post

    await db.commit()

    if can_post:
        return LocationResponse(
            can_post=True,
            message=f"Welcome to Art Basel Miami! You can now post and like.",
            distance_km=round(distance_km, 2)
        )
    else:
        return LocationResponse(
            can_post=False,
            message=f"You're {round(distance_km, 2)} km from Art Basel Miami. Get closer to post and like!",
            distance_km=round(distance_km, 2)
        )


@router.delete("/me", response_model=DeleteAccountResponse)
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Permanently delete user account and all associated data.

    This endpoint:
    1. Deletes all user likes
    2. Deletes all user posts (and associated likes on those posts)
    3. Deletes all check-ins
    4. Deletes all follows (as follower and following)
    5. Deletes all refresh tokens
    6. Deletes profile picture file from disk
    7. Deletes user account

    All operations are performed in a transaction with rollback on failure.
    """
    try:
        deleted_counts = {
            "likes": 0,
            "posts": 0,
            "check_ins": 0,
            "follows": 0,
            "refresh_tokens": 0,
            "files": 0
        }

        # 1. Delete user's likes
        result = await db.execute(
            delete(Like).where(Like.user_id == current_user.id)
        )
        deleted_counts["likes"] = result.rowcount

        # 2. Get all user posts to delete associated likes and media
        posts_result = await db.execute(
            select(Post).where(Post.user_id == current_user.id)
        )
        user_posts = posts_result.scalars().all()
        post_ids = [post.id for post in user_posts]

        # Delete likes on user's posts
        if post_ids:
            await db.execute(
                delete(Like).where(Like.post_id.in_(post_ids))
            )

        # Delete media files associated with posts
        for post in user_posts:
            if post.media_url:
                media_path = Path(settings.UPLOAD_DIR) / post.media_url.lstrip("/files/")
                if media_path.exists():
                    try:
                        os.remove(media_path)
                        deleted_counts["files"] += 1
                    except Exception as e:
                        print(f"Warning: Failed to delete media file {media_path}: {e}")

        # Delete user's posts
        if post_ids:
            result = await db.execute(
                delete(Post).where(Post.id.in_(post_ids))
            )
            deleted_counts["posts"] = result.rowcount

        # 3. Delete check-ins
        result = await db.execute(
            delete(CheckIn).where(CheckIn.user_id == current_user.id)
        )
        deleted_counts["check_ins"] = result.rowcount

        # 4. Delete follows (as follower)
        result = await db.execute(
            delete(Follow).where(Follow.follower_id == current_user.id)
        )
        follow_count = result.rowcount

        # Delete follows (as following)
        result = await db.execute(
            delete(Follow).where(Follow.following_id == current_user.id)
        )
        follow_count += result.rowcount
        deleted_counts["follows"] = follow_count

        # 5. Delete refresh tokens
        result = await db.execute(
            delete(RefreshToken).where(RefreshToken.user_id == current_user.id)
        )
        deleted_counts["refresh_tokens"] = result.rowcount

        # 6. Delete profile picture file
        if current_user.profile_picture:
            profile_pic_path = Path(settings.UPLOAD_DIR) / current_user.profile_picture.lstrip("/files/")
            if profile_pic_path.exists():
                try:
                    os.remove(profile_pic_path)
                    deleted_counts["files"] += 1
                except Exception as e:
                    print(f"Warning: Failed to delete profile picture {profile_pic_path}: {e}")

        # 7. Delete user account
        await db.delete(current_user)

        # Commit all changes
        await db.commit()

        return DeleteAccountResponse(
            success=True,
            message="Account and all associated data permanently deleted",
            deleted_data=deleted_counts
        )

    except Exception as e:
        # Rollback on any error
        await db.rollback()
        print(f"Error deleting account: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete account: {str(e)}"
        )


def generate_qr_token(user_id: int) -> str:
    """Generate a unique QR token for a user using SHA-256 hash"""
    data = f"{user_id}{settings.QR_SECRET_SALT}"
    return hashlib.sha256(data.encode()).hexdigest()


@router.get("/me/qr-token", response_model=QRTokenResponse)
async def get_qr_token(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get or generate QR token for current user.

    The QR token is a static hash that never expires and can be shared
    via QR code for mutual connections.
    """
    # Generate token if doesn't exist
    if not current_user.qr_token:
        current_user.qr_token = generate_qr_token(current_user.id)
        await db.commit()
        await db.refresh(current_user)

    return QRTokenResponse(qr_token=current_user.qr_token)


@router.post("/qr-connect", response_model=QRConnectResponse)
async def qr_connect(
    request: QRConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Connect with another user via scanned QR code.

    Creates mutual follow relationship - both users follow each other.
    """
    # Look up user by QR token
    result = await db.execute(
        select(User).where(User.qr_token == request.qr_token)
    )
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=404, detail="Invalid QR code")

    # Can't connect to yourself
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot connect to yourself")

    # Check if already following
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == target_user.id
        )
    )
    existing_follow = result.scalar_one_or_none()

    if existing_follow:
        raise HTTPException(status_code=400, detail="Already connected")

    # Create mutual follows
    follow1 = Follow(follower_id=current_user.id, following_id=target_user.id)
    follow2 = Follow(follower_id=target_user.id, following_id=current_user.id)

    db.add(follow1)
    db.add(follow2)
    await db.commit()

    return QRConnectResponse(
        success=True,
        message=f"Connected with @{target_user.nickname or target_user.username}",
        connected_user=SimpleUserResponse(
            id=target_user.id,
            nickname=target_user.nickname,
            first_name=target_user.first_name,
            last_name=target_user.last_name,
            profile_picture=target_user.profile_picture,
            employer=target_user.employer
        )
    )
