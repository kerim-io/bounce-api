from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid
from pathlib import Path
import aiofiles
import logging

from db.database import get_async_session
from db.models import Post, User, Like
from api.dependencies import get_current_user
from core.config import settings
from services.activity_clustering import get_activity_clusters
from api.routes.websocket import broadcast_activity_clusters

router = APIRouter(prefix="/posts", tags=["posts"])
logger = logging.getLogger(__name__)


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """Upload an image and return the URL"""
    # Allowed image extensions and MIME types
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}
    ALLOWED_MIME_TYPES = {
        "image/jpeg", "image/png", "image/gif", "image/webp",
        "image/heic", "image/heif"
    }

    # Validate file type by MIME type
    if not file.content_type or file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
        )

    # Validate file extension
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required"
        )

    file_extension = Path(file.filename).suffix.lower()
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file extension. Allowed extensions: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Validate file size (10MB max)
    try:
        contents = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read uploaded file"
        )

    if len(contents) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty"
        )

    if len(contents) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum allowed size of {settings.MAX_FILE_SIZE // (1024 * 1024)}MB"
        )

    # Generate unique filename
    unique_filename = f"{uuid.uuid4()}{file_extension}"

    # Ensure upload directory exists
    upload_dir = Path(settings.UPLOAD_DIR)
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create upload directory"
        )

    # Save file asynchronously
    upload_path = upload_dir / unique_filename
    try:
        async with aiofiles.open(upload_path, "wb") as f:
            await f.write(contents)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded file"
        )

    # Return URL
    file_url = f"/files/{unique_filename}"

    logger.info(
        "Image uploaded successfully",
        extra={
            "user_id": current_user.id,
            "uploaded_filename": unique_filename,
            "size_bytes": len(contents),
            "mime_type": file.content_type
        }
    )

    return {
        "url": file_url,
        "filename": unique_filename
    }


class PostCreate(BaseModel):
    content: str
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    venue_name: Optional[str] = None
    venue_id: Optional[str] = None


class PostResponse(BaseModel):
    id: int
    user_id: int
    username: Optional[str]
    content: str
    timestamp: datetime
    profile_pic_url: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    venue_name: Optional[str] = None
    venue_id: Optional[str] = None
    likes_count: int = 0
    is_liked_by_current_user: bool = False

    class Config:
        from_attributes = True


class LikeResponse(BaseModel):
    likes_count: int
    is_liked: bool


@router.post("/", response_model=PostResponse)
async def create_post(
    post_data: PostCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Create a new post with text and/or media"""
    # Validate content
    content = post_data.content.strip()

    # Allow empty content if media is present
    if not content and not post_data.media_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post must have content or media"
        )

    # Validate content length (max 2000 chars)
    if content and len(content) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post content exceeds maximum length of 2000 characters"
        )

    # Validate coordinates if provided
    if post_data.latitude is not None and post_data.longitude is not None:
        if not (-90 <= post_data.latitude <= 90):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Latitude must be between -90 and 90"
            )
        if not (-180 <= post_data.longitude <= 180):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Longitude must be between -180 and 180"
            )

    try:
        post = Post(
            user_id=current_user.id,
            content=content,
            media_url=post_data.media_url,
            media_type=post_data.media_type,
            latitude=post_data.latitude,
            longitude=post_data.longitude,
            venue_name=post_data.venue_name,
            venue_id=post_data.venue_id
        )
        db.add(post)
        await db.commit()
        await db.refresh(post)

        logger.info(
            "Post created successfully",
            extra={
                "user_id": current_user.id,
                "post_id": post.id,
                "has_media": bool(post.media_url),
                "media_type": post.media_type,
                "has_location": bool(post.latitude and post.longitude),
                "has_venue": bool(post.venue_name),
                "venue_name": post.venue_name,
                "content_length": len(content) if content else 0
            }
        )

        # Broadcast updated activity clusters if post has location
        if post.latitude is not None and post.longitude is not None:
            try:
                clusters = await get_activity_clusters(db)
                cluster_data = [
                    {
                        "cluster_id": c.cluster_id,
                        "latitude": c.latitude,
                        "longitude": c.longitude,
                        "count": c.count,
                        "venue_name": c.venue_name,
                        "last_activity": c.last_activity.isoformat()
                    }
                    for c in clusters
                ]
                await broadcast_activity_clusters(cluster_data)
            except Exception as cluster_err:
                logger.warning("Failed to broadcast activity clusters", extra={"error": str(cluster_err)})

        return PostResponse(
            id=post.id,
            user_id=post.user_id,
            username=current_user.nickname,
            content=post.content,
            timestamp=post.created_at,
            profile_pic_url=current_user.profile_picture,
            media_url=post.media_url,
            media_type=post.media_type,
            latitude=post.latitude,
            longitude=post.longitude,
            venue_name=post.venue_name,
            venue_id=post.venue_id
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create post"
        )


@router.get("/feed", response_model=List[PostResponse])
async def get_feed(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get feed of posts with likes (optimized single query)"""
    from sqlalchemy import case

    # Optimized single query with aggregations and conditional logic
    stmt = (
        select(
            Post,
            User,
            func.count(Like.id).label('likes_count'),
            func.max(case((Like.user_id == current_user.id, 1), else_=0)).label('is_liked')
        )
        .join(User, Post.user_id == User.id)
        .outerjoin(Like, Post.id == Like.post_id)
        .group_by(Post.id, User.id)
        .order_by(desc(Post.created_at))
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        PostResponse(
            id=post.id,
            user_id=post.user_id,
            username=user.nickname,
            content=post.content,
            timestamp=post.created_at,
            profile_pic_url=user.profile_picture,
            media_url=post.media_url,
            media_type=post.media_type,
            latitude=post.latitude,
            longitude=post.longitude,
            venue_name=post.venue_name,
            venue_id=post.venue_id,
            likes_count=likes_count or 0,
            is_liked_by_current_user=bool(is_liked)
        )
        for post, user, likes_count, is_liked in rows
    ]


@router.get("/by-time", response_model=List[PostResponse])
async def get_posts_by_time(
    date: str,  # YYYY-MM-DD
    hour: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Get posts by specific date/hour for timeline scrubbing (optimized single query)"""
    from datetime import datetime, timedelta
    from sqlalchemy import case

    # Validate date format
    try:
        target_date = datetime.fromisoformat(date)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Expected YYYY-MM-DD"
        )

    # Validate hour if provided
    if hour is not None:
        if not isinstance(hour, int) or not (0 <= hour <= 23):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hour must be an integer between 0 and 23"
            )

    if hour is not None:
        start_time = target_date.replace(hour=hour, minute=0, second=0)
        end_time = start_time + timedelta(hours=1)
    else:
        start_time = target_date.replace(hour=0, minute=0, second=0)
        end_time = start_time + timedelta(days=1)

    # Optimized single query with aggregations
    stmt = (
        select(
            Post,
            User,
            func.count(Like.id).label('likes_count'),
            func.max(case((Like.user_id == current_user.id, 1), else_=0)).label('is_liked')
        )
        .join(User, Post.user_id == User.id)
        .outerjoin(Like, Post.id == Like.post_id)
        .where(Post.created_at >= start_time)
        .where(Post.created_at < end_time)
        .group_by(Post.id, User.id)
        .order_by(desc(Post.created_at))
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        PostResponse(
            id=post.id,
            user_id=post.user_id,
            username=user.nickname,
            content=post.content,
            timestamp=post.created_at,
            profile_pic_url=user.profile_picture,
            media_url=post.media_url,
            media_type=post.media_type,
            latitude=post.latitude,
            longitude=post.longitude,
            venue_name=post.venue_name,
            venue_id=post.venue_id,
            likes_count=likes_count or 0,
            is_liked_by_current_user=bool(is_liked)
        )
        for post, user, likes_count, is_liked in rows
    ]
