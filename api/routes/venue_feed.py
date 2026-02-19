from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import base64
import json
import logging
import httpx

from db.database import get_async_session
from db.models import VenueFeedMessage, CheckIn, User, Place
from api.dependencies import get_current_user
from api.routes.websocket import manager
from api.routes.checkins import CHECKIN_EXPIRY_HOURS
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/venue-feed", tags=["venue-feed"])

MAX_TEXT_LENGTH = 500
DEFAULT_PAGE_SIZE = 50


async def verify_active_checkin(db: AsyncSession, user_id: int, place_id: str) -> bool:
    """Check if user has an active check-in at this venue."""
    expiry_time = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)
    result = await db.execute(
        select(CheckIn.id).where(
            and_(
                CheckIn.user_id == user_id,
                CheckIn.place_id == place_id,
                CheckIn.is_active == True,
                CheckIn.last_seen_at >= expiry_time,
            )
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


def _format_message(msg: VenueFeedMessage, user: User, ws_safe: bool = False) -> dict:
    """Format a feed message. When ws_safe=True, strip large base64 blobs."""
    image = msg.image
    profile_pic = user.profile_picture or user.instagram_profile_pic
    if ws_safe:
        image = None
        if profile_pic and profile_pic.startswith("data:"):
            profile_pic = None
    return {
        "id": msg.id,
        "place_id": msg.place_id,
        "user_id": msg.user_id,
        "nickname": user.nickname,
        "profile_picture": profile_pic,
        "text": msg.text,
        "image": image,
        "has_image": msg.image is not None,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


# ---------- REST endpoints ----------

class PostMessageRequest(BaseModel):
    text: str


class FeedMessageResponse(BaseModel):
    id: int
    place_id: str
    user_id: int
    nickname: Optional[str]
    profile_picture: Optional[str]
    text: Optional[str]
    image: Optional[str]
    created_at: Optional[str]


class FeedResponse(BaseModel):
    place_id: str
    messages: List[FeedMessageResponse]
    has_more: bool


@router.get("/{place_id}", response_model=FeedResponse)
async def get_venue_feed(
    place_id: str,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    before_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Read venue feed (paginated). Any authenticated user can read."""
    query = (
        select(VenueFeedMessage, User)
        .join(User, VenueFeedMessage.user_id == User.id)
        .where(and_(VenueFeedMessage.place_id == place_id, VenueFeedMessage.is_hidden == False))
    )
    if before_id is not None:
        query = query.where(VenueFeedMessage.id < before_id)

    query = query.order_by(desc(VenueFeedMessage.id)).limit(limit + 1)
    result = await db.execute(query)
    rows = result.all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    messages = [_format_message(msg, user) for msg, user in rows]

    return FeedResponse(place_id=place_id, messages=messages, has_more=has_more)


@router.post("/{place_id}")
async def post_venue_message(
    place_id: str,
    body: PostMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Post a text message to the venue feed. Must be checked in."""
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    if len(body.text) > MAX_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail=f"Text exceeds {MAX_TEXT_LENGTH} characters")

    if not await verify_active_checkin(db, current_user.id, place_id):
        raise HTTPException(status_code=403, detail="You must be checked in to this venue to post")

    # Resolve places FK
    place_result = await db.execute(select(Place).where(Place.place_id == place_id))
    place = place_result.scalar_one_or_none()

    msg = VenueFeedMessage(
        place_id=place_id,
        places_fk_id=place.id if place else None,
        user_id=current_user.id,
        text=body.text.strip(),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    payload = {
        "type": "venue_feed_message",
        **_format_message(msg, current_user),
    }
    await manager.send_to_venue_feed(place_id, payload)

    return payload


@router.post("/{place_id}/image")
async def post_venue_image(
    place_id: str,
    image: UploadFile = File(...),
    text: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Post an image (with optional text) to the venue feed. Must be checked in."""
    if text and len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail=f"Text exceeds {MAX_TEXT_LENGTH} characters")

    # Validate file type
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    if image.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only JPEG, PNG, WEBP allowed")

    content = await image.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds maximum allowed size of {settings.MAX_FILE_SIZE} bytes",
        )

    if not await verify_active_checkin(db, current_user.id, place_id):
        raise HTTPException(status_code=403, detail="You must be checked in to this venue to post")

    content_type = image.content_type or "image/jpeg"
    base64_data = base64.b64encode(content).decode("utf-8")
    data_uri = f"data:{content_type};base64,{base64_data}"

    place_result = await db.execute(select(Place).where(Place.place_id == place_id))
    place = place_result.scalar_one_or_none()

    msg = VenueFeedMessage(
        place_id=place_id,
        places_fk_id=place.id if place else None,
        user_id=current_user.id,
        text=text.strip() if text else None,
        image=data_uri,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # WS broadcast without image data (too large for WS frame)
    ws_payload = {
        "type": "venue_feed_message",
        **_format_message(msg, current_user, ws_safe=True),
    }
    await manager.send_to_venue_feed(place_id, ws_payload)

    # REST response — strip image (client already has it), just return metadata
    return {
        "type": "venue_feed_message",
        **_format_message(msg, current_user, ws_safe=True),
    }


# ---------- Moderation ----------

CATEGORIZE_PROMPT = """Categorize this reported social media message in one short phrase (e.g. "spam", "harassment", "hate speech", "inappropriate image", "off-topic", "other"). Respond with ONLY the category, nothing else."""


async def _groq_categorize(text: str):
    """Fire-and-forget: ask Groq to categorize a reported message. Returns category string."""
    if not settings.GROQ_API_KEY:
        return "uncategorized"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "max_tokens": 20,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": CATEGORIZE_PROMPT},
                        {"role": "user", "content": text or "(image only, no text)"},
                    ],
                },
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq categorize error: {e}")
    return "uncategorized"


@router.post("/report/{message_id}")
async def report_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Report a message. Groq categorizes it for records. Message stays visible."""
    result = await db.execute(
        select(VenueFeedMessage).where(VenueFeedMessage.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # Categorize in background, store for admin review
    import asyncio
    async def _categorize_and_store():
        from db.database import create_async_session
        reason = await _groq_categorize(msg.text)
        async with create_async_session() as session:
            result = await session.execute(
                select(VenueFeedMessage).where(VenueFeedMessage.id == message_id)
            )
            m = result.scalar_one_or_none()
            if m:
                m.moderation_reason = reason
                await session.commit()
        logger.info(f"Report #{message_id} categorized: {reason}")
    asyncio.create_task(_categorize_and_store())

    return {"reported": True, "message_id": message_id}


# ---------- WebSocket endpoint ----------

@router.websocket("/ws/{place_id}")
async def venue_feed_websocket(
    websocket: WebSocket,
    place_id: str,
    token: str = Query(...),
):
    """Subscribe to real-time venue feed updates. Read-only — posting is via REST."""
    from services.auth_service import decode_access_token
    from jose import JWTError

    try:
        payload = decode_access_token(token)
        int(payload.get("sub"))  # validate user_id present
    except (JWTError, ValueError, TypeError) as e:
        logger.warning(f"Venue feed WS auth failed: {e}")
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect_venue_feed(websocket, place_id)
    logger.debug(f"Venue feed WS connected: place_id={place_id}")

    try:
        await websocket.send_json({"type": "connected", "place_id": place_id})
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.debug(f"Venue feed WS disconnected: place_id={place_id}")
    except Exception as e:
        logger.error(f"Venue feed WS error for place_id={place_id}: {e}")
    finally:
        manager.disconnect_venue_feed(websocket, place_id)
