from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from db.database import get_async_session
from db.models import Post, Like, User
from api.dependencies import get_current_user
from api.routes.websocket import manager

router = APIRouter(prefix="/posts", tags=["likes"])


class LikeResponse(BaseModel):
    likes_count: int
    is_liked: bool


@router.post("/{post_id}/like", response_model=LikeResponse)
async def like_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Like a post (toggle)"""
    # Check if post exists
    post_result = await db.execute(select(Post).where(Post.id == post_id))
    post = post_result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Check if already liked
    like_result = await db.execute(
        select(Like).where(
            Like.user_id == current_user.id,
            Like.post_id == post_id
        )
    )
    existing_like = like_result.scalar_one_or_none()

    if existing_like:
        # Unlike
        await db.delete(existing_like)
        await db.commit()
        is_liked = False
    else:
        # Like
        new_like = Like(user_id=current_user.id, post_id=post_id)
        db.add(new_like)
        await db.commit()
        is_liked = True

    # Get updated count
    count_result = await db.execute(
        select(func.count(Like.id)).where(Like.post_id == post_id)
    )
    likes_count = count_result.scalar()

    # Broadcast like update to all connected clients via WebSocket
    await manager.broadcast({
        "type": "like_update",
        "post_id": post_id,
        "likes_count": likes_count,
        "is_liked_by_current_user": is_liked
    })

    print(f"🔔 Broadcasting like update: post_id={post_id}, likes_count={likes_count}, is_liked={is_liked}")

    return LikeResponse(likes_count=likes_count, is_liked=is_liked)


@router.delete("/{post_id}/like", response_model=LikeResponse)
async def unlike_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Unlike a post"""
    # Check if post exists
    post_result = await db.execute(select(Post).where(Post.id == post_id))
    post = post_result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Find and delete like
    like_result = await db.execute(
        select(Like).where(
            Like.user_id == current_user.id,
            Like.post_id == post_id
        )
    )
    existing_like = like_result.scalar_one_or_none()

    if existing_like:
        await db.delete(existing_like)
        await db.commit()

    # Get updated count
    count_result = await db.execute(
        select(func.count(Like.id)).where(Like.post_id == post_id)
    )
    likes_count = count_result.scalar()

    return LikeResponse(likes_count=likes_count, is_liked=False)
