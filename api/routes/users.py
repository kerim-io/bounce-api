from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_, func
from pydantic import BaseModel
from typing import Optional, List
import aiofiles
from pathlib import Path
import uuid
import os
import hashlib
import logging
from datetime import datetime
from math import radians, cos, sin, asin, sqrt

from db.database import get_async_session
from db.models import User, Follow, Post, Like, CheckIn, RefreshToken, Livestream
from api.dependencies import get_current_user, limiter
from core.config import settings
from api.routes.websocket import manager as ws_manager
from services.geofence import haversine_distance
import re

router = APIRouter(prefix="/users", tags=["users"])
logger = logging.getLogger(__name__)


def sanitize_nickname(nickname: str) -> str:
    """
    Sanitize nickname to only allow letters, numbers, and underscores.
    Spaces become underscores, other characters are removed.
    """
    # Replace spaces with underscores
    nickname = nickname.replace(" ", "_")
    # Remove any character that isn't alphanumeric or underscore
    nickname = re.sub(r'[^a-zA-Z0-9_]', '', nickname)
    # Remove consecutive underscores
    nickname = re.sub(r'_+', '_', nickname)
    # Strip leading/trailing underscores
    nickname = nickname.strip('_')
    return nickname.lower()


class ProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    nickname: Optional[str] = None
    employer: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    profile_picture_url: Optional[str] = None
    instagram_handle: Optional[str] = None
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
    instagram_handle: Optional[str] = None
    has_profile: bool
    # Privacy flags (only shown to owner)
    phone_visible: Optional[bool] = None
    email_visible: Optional[bool] = None
    # Social handles
    instagram_handle: Optional[str] = None
    instagram_profile_pic: Optional[str] = None
    linkedin_handle: Optional[str] = None
    # Stats
    posts_count: int = 0
    followers_count: int = 0
    following_count: int = 0

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
    instagram_handle: Optional[str] = None

    class Config:
        from_attributes = True


class PublicProfileResponse(BaseModel):
    """Public profile response with stats for viewing other users"""
    id: int
    first_name: Optional[str]
    last_name: Optional[str]
    nickname: Optional[str]
    employer: Optional[str]
    phone: Optional[str] = None
    email: Optional[str] = None
    profile_picture: Optional[str]
    has_profile: bool
    # Stats
    posts_count: int
    followers_count: int
    following_count: int
    # Follow state for current user
    is_followed_by_current_user: bool

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
    """Response containing user's QR code deep link URL"""
    qr_token: str
    qr_url: str  # Full deep link URL for QR code generation


class QRConnectRequest(BaseModel):
    """Request to connect via QR code"""
    qr_token: str


class QRConnectResponse(BaseModel):
    """Response after QR code connection"""
    success: bool
    message: str
    connected_user: SimpleUserResponse


class UserSearchResult(BaseModel):
    """Individual user result for search autocomplete"""
    id: int
    nickname: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    profile_picture: Optional[str]
    instagram_handle: Optional[str]
    match_type: str  # 'nickname' or 'instagram'

    class Config:
        from_attributes = True


class UserSearchResponse(BaseModel):
    """Response for user search autocomplete"""
    query: str
    results: List[UserSearchResult]
    total_count: int


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Get current user profile"""
    return current_user


@router.get("/me/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get current user full profile with stats"""
    from sqlalchemy import func

    # Get posts count
    posts_result = await db.execute(
        select(func.count(Post.id)).where(Post.user_id == current_user.id)
    )
    posts_count = posts_result.scalar() or 0

    # Get followers count (users following this user)
    followers_result = await db.execute(
        select(func.count(Follow.id)).where(Follow.following_id == current_user.id)
    )
    followers_count = followers_result.scalar() or 0

    # Get following count (users this user follows)
    following_result = await db.execute(
        select(func.count(Follow.id)).where(Follow.follower_id == current_user.id)
    )
    following_count = following_result.scalar() or 0

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
        instagram_handle=current_user.instagram_handle,
        instagram_profile_pic=current_user.instagram_profile_pic,
        linkedin_handle=current_user.linkedin_handle,
        posts_count=posts_count,
        followers_count=followers_count,
        following_count=following_count
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
        sanitized = sanitize_nickname(profile_data.nickname)
        if not sanitized:
            raise HTTPException(status_code=400, detail="Nickname must contain at least one letter or number")
        current_user.nickname = sanitized
    if profile_data.employer is not None:
        current_user.employer = profile_data.employer
    if profile_data.phone is not None:
        current_user.phone = profile_data.phone
    if profile_data.email is not None:
        current_user.email = profile_data.email
    if profile_data.profile_picture_url is not None:
        current_user.profile_picture = profile_data.profile_picture_url
    if profile_data.instagram_handle is not None:
        # Normalize instagram handle: remove @ prefix if present, lowercase
        handle = profile_data.instagram_handle.strip().lstrip('@').lower()
        current_user.instagram_handle = handle if handle else None

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
        email_visible=current_user.email_visible,
        instagram_handle=current_user.instagram_handle,
        instagram_profile_pic=current_user.instagram_profile_pic,
        linkedin_handle=current_user.linkedin_handle
    )


class InstagramHandleUpdate(BaseModel):
    instagram_handle: Optional[str] = None


@router.put("/me/instagram")
async def update_instagram_handle(
    data: InstagramHandleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Update current user's Instagram handle and fetch their profile pic"""
    import httpx
    import json

    handle = data.instagram_handle

    # Clean handle - remove @ if present
    if handle:
        handle = handle.lstrip("@").strip()
        if len(handle) > 30:
            raise HTTPException(status_code=400, detail="Instagram handle too long")

    current_user.instagram_handle = handle if handle else None
    current_user.instagram_profile_pic = None  # Reset pic

    # Fetch profile pic if handle provided
    if handle:
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
            "Accept": "*/*",
            "X-IG-App-ID": "936619743392459",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://www.instagram.com/api/v1/users/web_profile_info/?username={handle}",
                    headers=headers,
                    timeout=10.0
                )

                if response.status_code == 200:
                    try:
                        data = response.json()
                        user_data = data.get("data", {}).get("user", {})
                        pic_url = user_data.get("profile_pic_url_hd") or user_data.get("profile_pic_url")
                        if pic_url:
                            current_user.instagram_profile_pic = pic_url
                    except (json.JSONDecodeError, KeyError):
                        pass

                # Fallback to scraping
                if not current_user.instagram_profile_pic:
                    response = await client.get(
                        f"https://www.instagram.com/{handle}/",
                        headers={"User-Agent": headers["User-Agent"], "Accept": "text/html"},
                        follow_redirects=True,
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        import re
                        match = re.search(r'"profile_pic_url_hd":"([^"]+)"', response.text)
                        if match:
                            current_user.instagram_profile_pic = match.group(1).replace("\\u0026", "&").replace("\\/", "/")

        except Exception as e:
            logger.warning(f"Failed to fetch Instagram profile pic for {handle}: {e}")

    await db.commit()

    return {
        "success": True,
        "instagram_handle": current_user.instagram_handle,
        "instagram_profile_pic": current_user.instagram_profile_pic
    }


class InstagramLookupRequest(BaseModel):
    handle: str


class LinkedInHandleUpdate(BaseModel):
    linkedin_handle: Optional[str] = None


@router.put("/me/linkedin")
async def update_linkedin_handle(
    data: LinkedInHandleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Update current user's LinkedIn handle (username from profile URL)"""
    handle = data.linkedin_handle

    # Clean handle - extract username if full URL provided
    if handle:
        handle = handle.strip()
        # Handle full URLs like linkedin.com/in/username
        if "linkedin.com/in/" in handle:
            handle = handle.split("linkedin.com/in/")[-1].strip("/").split("?")[0]
        if len(handle) > 100:
            raise HTTPException(status_code=400, detail="LinkedIn handle too long")

    current_user.linkedin_handle = handle if handle else None
    await db.commit()

    return {"success": True, "linkedin_handle": current_user.linkedin_handle}


class LinkedInLookupRequest(BaseModel):
    handle: str


@router.post("/linkedin/lookup")
async def lookup_linkedin_profile(
    request: LinkedInLookupRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Fetch LinkedIn profile pic URL for a given handle.

    Note: LinkedIn is very restrictive about scraping. This may not always work.
    """
    import httpx

    handle = request.handle.strip()
    if not handle:
        raise HTTPException(status_code=400, detail="Handle required")

    # Clean handle - extract username if full URL provided
    if "linkedin.com/in/" in handle:
        handle = handle.split("linkedin.com/in/")[-1].strip("/").split("?")[0]

    profile_pic_url = None
    full_name = None

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://www.linkedin.com/in/{handle}/",
                headers=headers,
                follow_redirects=True,
                timeout=10.0
            )

            if response.status_code == 200:
                html = response.text
                import re

                # Try to find profile image in various formats
                # LinkedIn often uses data-delayed-url or img tags with specific classes
                patterns = [
                    r'"profilePicture"[^}]*"displayImageUrl":"([^"]+)"',
                    r'data-delayed-url="(https://media\.licdn\.com/[^"]+)"',
                    r'<img[^>]*class="[^"]*profile-photo[^"]*"[^>]*src="([^"]+)"',
                    r'<img[^>]*src="(https://media\.licdn\.com/dms/image/[^"]+)"',
                    r'"picture":"(https://media\.licdn\.com/[^"]+)"',
                ]

                for pattern in patterns:
                    match = re.search(pattern, html)
                    if match:
                        profile_pic_url = match.group(1).replace("\\u002F", "/").replace("\\/", "/")
                        break

                # Try to get full name
                name_patterns = [
                    r'<title>([^|<]+?)(?:\s*[-|]|\s*\|)',
                    r'"firstName":"([^"]+)"[^}]*"lastName":"([^"]+)"',
                    r'<h1[^>]*>([^<]+)</h1>',
                ]

                for pattern in name_patterns:
                    match = re.search(pattern, html)
                    if match:
                        if match.lastindex == 2:
                            full_name = f"{match.group(1)} {match.group(2)}"
                        else:
                            full_name = match.group(1).strip()
                        break

    except Exception as e:
        logger.warning(f"LinkedIn lookup error for {handle}: {e}")

    return {
        "handle": handle,
        "profile_url": f"https://www.linkedin.com/in/{handle}/",
        "profile_pic_url": profile_pic_url,
        "full_name": full_name,
        "success": profile_pic_url is not None
    }


@router.post("/instagram/lookup")
async def lookup_instagram_profile(
    request: InstagramLookupRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Fetch Instagram profile pic URL for a given handle.

    Tries multiple methods:
    1. Instagram's web API endpoint
    2. Scraping the profile page HTML
    """
    import httpx
    import json

    handle = request.handle.lstrip("@").strip()
    if not handle:
        raise HTTPException(status_code=400, detail="Handle required")

    profile_pic_url = None
    full_name = None

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-IG-App-ID": "936619743392459",
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        async with httpx.AsyncClient() as client:
            # Method 1: Try the web profile info endpoint
            response = await client.get(
                f"https://www.instagram.com/api/v1/users/web_profile_info/?username={handle}",
                headers=headers,
                timeout=10.0
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                    user_data = data.get("data", {}).get("user", {})
                    profile_pic_url = user_data.get("profile_pic_url_hd") or user_data.get("profile_pic_url")
                    full_name = user_data.get("full_name")
                except (json.JSONDecodeError, KeyError):
                    pass

            # Method 2: Fallback to scraping profile page
            if not profile_pic_url:
                response = await client.get(
                    f"https://www.instagram.com/{handle}/",
                    headers={
                        "User-Agent": headers["User-Agent"],
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    follow_redirects=True,
                    timeout=10.0
                )

                if response.status_code == 200:
                    html = response.text

                    # Try to find profile_pic_url_hd in JSON data
                    import re
                    match = re.search(r'"profile_pic_url_hd":"([^"]+)"', html)
                    if match:
                        profile_pic_url = match.group(1).replace("\\u0026", "&").replace("\\/", "/")
                    else:
                        # Try profile_pic_url
                        match = re.search(r'"profile_pic_url":"([^"]+)"', html)
                        if match:
                            profile_pic_url = match.group(1).replace("\\u0026", "&").replace("\\/", "/")
                        else:
                            # Fallback: og:image meta tag
                            match = re.search(r'property="og:image"\s+content="([^"]+)"', html)
                            if match:
                                profile_pic_url = match.group(1)

                    # Try to get full name
                    if not full_name:
                        match = re.search(r'"full_name":"([^"]*)"', html)
                        if match:
                            full_name = match.group(1)

    except Exception as e:
        logger.warning(f"Instagram lookup error for {handle}: {e}")

    return {
        "handle": handle,
        "profile_pic_url": profile_pic_url,
        "full_name": full_name,
        "success": profile_pic_url is not None
    }


@router.post("/me/profile-picture")
@limiter.limit("5/minute")
async def upload_profile_picture(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Upload profile picture (multipart/form-data)"""
    # Validate file type
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only JPEG, PNG, WEBP allowed")

    # Read and validate file size
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds maximum allowed size of {settings.MAX_FILE_SIZE} bytes"
        )

    # Generate unique filename
    ext = Path(file.filename).suffix if file.filename else ".jpg"
    filename = f"profile_{current_user.id}_{uuid.uuid4().hex[:8]}{ext}"

    # Save to uploads directory
    upload_dir = Path(settings.UPLOAD_DIR) / "profile_pictures"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename

    async with aiofiles.open(file_path, "wb") as f:
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

    # Send in-app notification to the followed user
    notification_payload = {
        "type": "notification",
        "notification_type": "new_follower",
        "message": f"{current_user.nickname or current_user.first_name} started following you",
        "actor": {
            "user_id": current_user.id,
            "nickname": current_user.nickname,
            "profile_picture": current_user.profile_picture
        }
    }

    logger.info(f"Sending follow notification to user {user_id}: {notification_payload}")
    sent = await ws_manager.send_to_user(user_id, notification_payload)
    logger.info(f"Follow notification sent to user {user_id}: {sent} (user connected: {user_id in ws_manager.active_connections})")

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


@router.get("/{user_id}/following", response_model=List[SimpleUserResponse])
async def get_user_following(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get list of users that a specific user is following"""
    # Verify user exists
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(User).join(
            Follow, Follow.following_id == User.id
        ).where(Follow.follower_id == user_id)
    )
    users = result.scalars().all()
    return [
        SimpleUserResponse(
            id=u.id,
            nickname=u.nickname,
            first_name=u.first_name,
            last_name=u.last_name,
            profile_picture=u.profile_picture,
            employer=u.employer
        )
        for u in users
    ]


@router.get("/{user_id}/followers", response_model=List[SimpleUserResponse])
async def get_user_followers(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get list of users following a specific user"""
    # Verify user exists
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(User).join(
            Follow, Follow.follower_id == User.id
        ).where(Follow.following_id == user_id)
    )
    users = result.scalars().all()
    return [
        SimpleUserResponse(
            id=u.id,
            nickname=u.nickname,
            first_name=u.first_name,
            last_name=u.last_name,
            profile_picture=u.profile_picture,
            employer=u.employer
        )
        for u in users
    ]


@router.get("/{user_id}/profile", response_model=PublicProfileResponse)
async def get_user_profile(
    user_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get another user's profile with privacy controls and stats.

    Phone/email only visible if:
    - User has made them visible (phone_visible/email_visible = True) AND
    - Requesting user is geolocated at Art Basel Miami (can_post = True)

    Returns posts count, followers count, following count, and follow state.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get posts count
    posts_result = await db.execute(
        select(func.count(Post.id)).where(Post.user_id == user_id)
    )
    posts_count = posts_result.scalar() or 0

    # Get followers count (users following this user)
    followers_result = await db.execute(
        select(func.count(Follow.id)).where(Follow.following_id == user_id)
    )
    followers_count = followers_result.scalar() or 0

    # Get following count (users this user follows)
    following_result = await db.execute(
        select(func.count(Follow.id)).where(Follow.follower_id == user_id)
    )
    following_count = following_result.scalar() or 0

    # Check if current user follows this user
    follow_check = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    is_followed = follow_check.scalar_one_or_none() is not None

    # Conditional privacy: only show phone/email to geolocated users
    can_see_private = current_user.can_post  # Geolocated at Art Basel Miami

    return PublicProfileResponse(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        nickname=user.nickname,
        employer=user.employer,
        phone=user.phone if (user.phone_visible and can_see_private) else None,
        email=user.email if (user.email_visible and can_see_private) else None,
        profile_picture=user.profile_picture,
        instagram_handle=user.instagram_handle,
        has_profile=user.has_profile,
        posts_count=posts_count,
        followers_count=followers_count,
        following_count=following_count,
        is_followed_by_current_user=is_followed
    )


# Removed duplicate haversine_distance function - now imported from services.geofence


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
    4. Deletes all livestreams
    5. Deletes all follows (as follower and following)
    6. Deletes all refresh tokens
    7. Deletes profile picture file from disk
    8. Deletes user account

    All operations are performed in a transaction with rollback on failure.
    """
    # Capture user_id for error logging before any operations
    user_id = current_user.id

    try:
        deleted_counts = {
            "likes": 0,
            "posts": 0,
            "check_ins": 0,
            "livestreams": 0,
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
                        logger.warning("Failed to delete media file", extra={"media_path": str(media_path), "error": str(e)})

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

        # 4. Delete livestreams
        result = await db.execute(
            delete(Livestream).where(Livestream.user_id == current_user.id)
        )
        deleted_counts["livestreams"] = result.rowcount

        # 5. Delete follows (as follower)
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

        # 6. Delete refresh tokens
        result = await db.execute(
            delete(RefreshToken).where(RefreshToken.user_id == current_user.id)
        )
        deleted_counts["refresh_tokens"] = result.rowcount

        # 7. Delete profile picture file
        if current_user.profile_picture:
            profile_pic_path = Path(settings.UPLOAD_DIR) / current_user.profile_picture.lstrip("/files/")
            if profile_pic_path.exists():
                try:
                    os.remove(profile_pic_path)
                    deleted_counts["files"] += 1
                except Exception as e:
                    logger.warning("Failed to delete profile picture", extra={"profile_pic_path": str(profile_pic_path), "error": str(e)})

        # 8. Delete user account
        await db.delete(current_user)

        # Commit all changes
        await db.commit()

        logger.info(
            "Account deleted successfully",
            extra={"user_id": user_id, "deleted_counts": deleted_counts}
        )

        return DeleteAccountResponse(
            success=True,
            message="Account and all associated data permanently deleted",
            deleted_data=deleted_counts
        )

    except Exception as e:
        # Rollback on any error
        await db.rollback()
        logger.error("Error deleting account", exc_info=True, extra={"user_id": user_id, "error": str(e)})
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

    # Build full deep link URL for QR code
    qr_url = f"{settings.QR_DEEP_LINK_SCHEME}{current_user.qr_token}"

    return QRTokenResponse(qr_token=current_user.qr_token, qr_url=qr_url)


@router.get("/{user_id}/qr-token", response_model=QRTokenResponse)
async def get_user_qr_token(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Get another user's QR code deep link URL.
    """
    # Look up the user
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Generate token if doesn't exist
    if not target_user.qr_token:
        target_user.qr_token = generate_qr_token(target_user.id)
        await db.commit()
        await db.refresh(target_user)

    # Build full deep link URL for QR code
    qr_url = f"{settings.QR_DEEP_LINK_SCHEME}{target_user.qr_token}"

    return QRTokenResponse(qr_token=target_user.qr_token, qr_url=qr_url)


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
            employer=target_user.employer,
            instagram_handle=target_user.instagram_handle
        )
    )


@router.get("/search", response_model=UserSearchResponse)
async def search_users(
    q: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Search users by nickname or Instagram handle for autocomplete.

    Designed for debounce-style search - returns matches as user types.
    Returns profile pictures for display in autocomplete dropdown.

    Parameters:
    - q: Search query (min 1 character). Searches both nickname and Instagram handle.
    - limit: Max results to return (default 10, max 50)

    Returns:
    - List of matching users with profile info and match_type indicator
    """
    # Validate query
    query = q.strip().lstrip('@').lower()
    if len(query) < 1:
        return UserSearchResponse(query=q, results=[], total_count=0)

    # Cap limit to prevent abuse
    limit = min(limit, 50)

    # Search for users matching nickname or instagram_handle (case-insensitive prefix match)
    # Uses ILIKE for case-insensitive matching with wildcard suffix for autocomplete
    search_pattern = f"{query}%"

    result = await db.execute(
        select(User)
        .where(
            User.is_active == True,
            User.id != current_user.id,  # Exclude current user
            or_(
                func.lower(User.nickname).like(search_pattern),
                func.lower(User.instagram_handle).like(search_pattern)
            )
        )
        .order_by(
            # Prioritize exact matches, then prefix matches
            func.length(User.nickname).asc()
        )
        .limit(limit)
    )
    users = result.scalars().all()

    # Build results with match type indicator
    search_results = []
    for user in users:
        # Determine which field matched
        nickname_lower = (user.nickname or "").lower()
        instagram_lower = (user.instagram_handle or "").lower()

        if nickname_lower.startswith(query):
            match_type = "nickname"
        elif instagram_lower.startswith(query):
            match_type = "instagram"
        else:
            match_type = "nickname"  # Fallback

        search_results.append(UserSearchResult(
            id=user.id,
            nickname=user.nickname,
            first_name=user.first_name,
            last_name=user.last_name,
            profile_picture=user.profile_picture,
            instagram_handle=user.instagram_handle,
            match_type=match_type
        ))

    return UserSearchResponse(
        query=q,
        results=search_results,
        total_count=len(search_results)
    )
