from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from collections import defaultdict
import logging

from db.database import get_async_session
from db.models import User, Conversation, DirectMessage, DirectMessageReaction, Bounce
from api.dependencies import get_current_user
from api.routes.websocket import manager as ws_manager
from services.tasks import enqueue_notification, payload_to_dict

router = APIRouter(prefix="/messages", tags=["messages"])
logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 2000
ALLOWED_REACTIONS = {"❤️", "😂", "😮", "😢", "🔥", "👍", "👎", "🎉"}


class SendMessageRequest(BaseModel):
    text: Optional[str] = Field(None, max_length=MAX_MESSAGE_LENGTH)
    client_id: Optional[str] = Field(None, max_length=64)  # UUID for optimistic-send dedupe
    reply_to_id: Optional[int] = None                      # message being replied to
    bounce_id: Optional[int] = None                        # bounce shared into the chat


class ReactRequest(BaseModel):
    emoji: str = Field(..., max_length=16)


class ConversationUser(BaseModel):
    id: int
    nickname: Optional[str]
    first_name: Optional[str]
    profile_picture: Optional[str]


class ConversationResponse(BaseModel):
    conversation_id: int
    other_user: ConversationUser
    last_message: Optional[Dict[str, Any]]
    unread_count: int
    last_message_at: datetime


def _normalized_pair(a: int, b: int) -> tuple:
    return (a, b) if a < b else (b, a)


async def _get_or_create_conversation(db: AsyncSession, user_a: int, user_b: int) -> Conversation:
    u1, u2 = _normalized_pair(user_a, user_b)
    result = await db.execute(
        select(Conversation).where(
            Conversation.user1_id == u1,
            Conversation.user2_id == u2
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        conversation = Conversation(user1_id=u1, user2_id=u2)
        db.add(conversation)
        await db.flush()
    return conversation


def _other_user_id(conversation: Conversation, me: int) -> int:
    return conversation.user2_id if conversation.user1_id == me else conversation.user1_id


def _is_participant(conversation: Conversation, user_id: int) -> bool:
    return user_id in (conversation.user1_id, conversation.user2_id)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _bounce_card(bounce: Bounce) -> dict:
    return {
        "id": bounce.id,
        "venue_name": bounce.venue_name,
        "venue_address": bounce.venue_address,
        "bounce_time": bounce.bounce_time.isoformat() if bounce.bounce_time else None,
        "is_now": bounce.is_now,
        "latitude": bounce.latitude,
        "longitude": bounce.longitude,
        "place_id": bounce.place_id,
        "status": bounce.status,
    }


async def _serialize_messages(
    db: AsyncSession, messages: List[DirectMessage]
) -> List[dict]:
    """Full message dicts with reply previews, reactions, and bounce cards — batch-loaded."""
    if not messages:
        return []

    msg_ids = [m.id for m in messages]
    reply_ids = [m.reply_to_id for m in messages if m.reply_to_id]
    bounce_ids = [m.bounce_id for m in messages if m.bounce_id]

    # Reactions grouped by message
    reactions_by_msg: Dict[int, list] = defaultdict(list)
    reaction_rows = await db.execute(
        select(DirectMessageReaction).where(DirectMessageReaction.message_id.in_(msg_ids))
    )
    for r in reaction_rows.scalars().all():
        reactions_by_msg[r.message_id].append({"user_id": r.user_id, "emoji": r.emoji})

    # Replied-to previews
    replies: Dict[int, dict] = {}
    if reply_ids:
        reply_rows = await db.execute(
            select(DirectMessage).where(DirectMessage.id.in_(reply_ids))
        )
        for rm in reply_rows.scalars().all():
            replies[rm.id] = {
                "id": rm.id,
                "sender_id": rm.sender_id,
                "text": None if rm.deleted_at else rm.text,
                "deleted": rm.deleted_at is not None,
                "is_bounce": rm.bounce_id is not None,
            }

    # Bounce cards
    bounces: Dict[int, dict] = {}
    if bounce_ids:
        bounce_rows = await db.execute(select(Bounce).where(Bounce.id.in_(bounce_ids)))
        for b in bounce_rows.scalars().all():
            bounces[b.id] = _bounce_card(b)

    return [_message_dict(m, reactions_by_msg, replies, bounces) for m in messages]


def _message_dict(
    message: DirectMessage,
    reactions_by_msg: Optional[Dict[int, list]] = None,
    replies: Optional[Dict[int, dict]] = None,
    bounces: Optional[Dict[int, dict]] = None,
) -> dict:
    reactions_by_msg = reactions_by_msg or {}
    replies = replies or {}
    bounces = bounces or {}
    deleted = message.deleted_at is not None
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "text": None if deleted else message.text,
        "client_id": message.client_id,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "read_at": message.read_at.isoformat() if message.read_at else None,
        "deleted": deleted,
        "reply_to_id": message.reply_to_id,
        "reply_to": replies.get(message.reply_to_id) if message.reply_to_id else None,
        "bounce_id": message.bounce_id,
        "bounce": bounces.get(message.bounce_id) if message.bounce_id else None,
        "reactions": reactions_by_msg.get(message.id, []),
    }


async def _serialize_one(db: AsyncSession, message: DirectMessage) -> dict:
    return (await _serialize_messages(db, [message]))[0]


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@router.get("/conversations", response_model=List[ConversationResponse])
async def get_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """All conversations for the current user, most recent first, with unread counts."""
    result = await db.execute(
        select(Conversation).where(
            or_(
                Conversation.user1_id == current_user.id,
                Conversation.user2_id == current_user.id
            )
        ).order_by(Conversation.last_message_at.desc())
    )
    conversations = result.scalars().all()
    if not conversations:
        return []

    conversation_ids = [c.id for c in conversations]

    last_msg_result = await db.execute(
        select(DirectMessage).where(
            DirectMessage.id.in_(
                select(func.max(DirectMessage.id))
                .where(DirectMessage.conversation_id.in_(conversation_ids))
                .group_by(DirectMessage.conversation_id)
            )
        )
    )
    last_messages = {m.conversation_id: m for m in last_msg_result.scalars().all()}
    serialized_last = {
        m.conversation_id: d
        for m, d in zip(
            last_messages.values(),
            await _serialize_messages(db, list(last_messages.values()))
        )
    }

    unread_result = await db.execute(
        select(DirectMessage.conversation_id, func.count(DirectMessage.id))
        .where(
            DirectMessage.conversation_id.in_(conversation_ids),
            DirectMessage.sender_id != current_user.id,
            DirectMessage.read_at.is_(None),
            DirectMessage.deleted_at.is_(None)
        )
        .group_by(DirectMessage.conversation_id)
    )
    unread_counts = dict(unread_result.all())

    other_ids = [_other_user_id(c, current_user.id) for c in conversations]
    users_result = await db.execute(select(User).where(User.id.in_(other_ids)))
    users = {u.id: u for u in users_result.scalars().all()}

    out = []
    for conversation in conversations:
        other = users.get(_other_user_id(conversation, current_user.id))
        if not other:
            continue
        out.append(ConversationResponse(
            conversation_id=conversation.id,
            other_user=ConversationUser(
                id=other.id,
                nickname=other.nickname,
                first_name=other.first_name,
                profile_picture=other.profile_picture or other.instagram_profile_pic,
            ),
            last_message=serialized_last.get(conversation.id),
            unread_count=unread_counts.get(conversation.id, 0),
            last_message_at=conversation.last_message_at,
        ))
    return out


@router.get("/with/{user_id}")
async def get_messages_with_user(
    user_id: int,
    before_id: Optional[int] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Message history with a user, newest first (paginate with before_id)."""
    limit = min(max(limit, 1), 100)

    u1, u2 = _normalized_pair(current_user.id, user_id)
    result = await db.execute(
        select(Conversation).where(
            Conversation.user1_id == u1,
            Conversation.user2_id == u2
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        return {"conversation_id": None, "messages": []}

    query = select(DirectMessage).where(DirectMessage.conversation_id == conversation.id)
    if before_id is not None:
        query = query.where(DirectMessage.id < before_id)
    query = query.order_by(DirectMessage.id.desc()).limit(limit)

    messages_result = await db.execute(query)
    messages = messages_result.scalars().all()

    return {
        "conversation_id": conversation.id,
        "messages": await _serialize_messages(db, list(messages)),
    }


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

@router.post("/to/{user_id}")
async def send_message(
    user_id: int,
    body: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Send a DM (optionally a reply and/or a shared bounce): persist, push over WS + APNs."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot message yourself")

    recipient_result = await db.execute(select(User).where(User.id == user_id))
    recipient = recipient_result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(status_code=404, detail="User not found")

    text = (body.text or "").strip() or None
    if not text and not body.bounce_id:
        raise HTTPException(status_code=400, detail="Message is empty")

    conversation = await _get_or_create_conversation(db, current_user.id, user_id)

    # Validate the replied-to message belongs to this conversation
    reply_to_id = None
    if body.reply_to_id:
        parent_result = await db.execute(
            select(DirectMessage).where(
                DirectMessage.id == body.reply_to_id,
                DirectMessage.conversation_id == conversation.id
            )
        )
        if parent_result.scalar_one_or_none():
            reply_to_id = body.reply_to_id

    # Validate the shared bounce exists
    bounce_id = None
    if body.bounce_id:
        bounce_result = await db.execute(select(Bounce).where(Bounce.id == body.bounce_id))
        if bounce_result.scalar_one_or_none():
            bounce_id = body.bounce_id

    # Dedupe retried optimistic sends (same client_id in this conversation)
    if body.client_id:
        existing_result = await db.execute(
            select(DirectMessage).where(
                DirectMessage.conversation_id == conversation.id,
                DirectMessage.sender_id == current_user.id,
                DirectMessage.client_id == body.client_id
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            return await _serialize_one(db, existing)

    message = DirectMessage(
        conversation_id=conversation.id,
        sender_id=current_user.id,
        text=text,
        client_id=body.client_id,
        reply_to_id=reply_to_id,
        bounce_id=bounce_id,
    )
    db.add(message)
    conversation.last_message_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(message)

    serialized = await _serialize_one(db, message)
    sender_name = current_user.nickname or current_user.first_name or "Someone"
    sender_pic = current_user.profile_picture or current_user.instagram_profile_pic

    # Realtime delivery to the recipient
    await ws_manager.send_to_user(user_id, {
        "type": "dm",
        "message": serialized,
        "sender": {
            "id": current_user.id,
            "nickname": current_user.nickname,
            "first_name": current_user.first_name,
            "profile_picture": sender_pic,
        },
    })

    # Push notification (deep-links into the chat via conversation_id)
    from services.apns_service import NotificationPayload, NotificationType
    if bounce_id and serialized.get("bounce"):
        push_body = f"📍 sent a bounce · {serialized['bounce']['venue_name']}"
    else:
        push_body = text if text and len(text) <= 120 else ((text or "")[:117] + "...")
    payload = NotificationPayload(
        notification_type=NotificationType.MESSAGE,
        title=sender_name,
        body=push_body,
        actor_id=current_user.id,
        actor_nickname=sender_name,
        actor_profile_picture=sender_pic,
        conversation_id=conversation.id,
    )
    enqueue_notification(user_id, payload_to_dict(payload))

    return serialized


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------

async def _load_message_for_participant(
    db: AsyncSession, message_id: int, user_id: int
) -> tuple:
    """Return (message, conversation) if the user participates, else raise 404."""
    result = await db.execute(select(DirectMessage).where(DirectMessage.id == message_id))
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == message.conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation or not _is_participant(conversation, user_id):
        raise HTTPException(status_code=404, detail="Message not found")
    return message, conversation


@router.post("/{message_id}/react")
async def react_to_message(
    message_id: int,
    body: ReactRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Set (or replace) the current user's reaction to a message."""
    if body.emoji not in ALLOWED_REACTIONS:
        raise HTTPException(status_code=400, detail="Unsupported reaction")

    message, conversation = await _load_message_for_participant(db, message_id, current_user.id)

    existing_result = await db.execute(
        select(DirectMessageReaction).where(
            DirectMessageReaction.message_id == message_id,
            DirectMessageReaction.user_id == current_user.id
        )
    )
    reaction = existing_result.scalar_one_or_none()
    if reaction:
        reaction.emoji = body.emoji
    else:
        db.add(DirectMessageReaction(
            message_id=message_id, user_id=current_user.id, emoji=body.emoji
        ))
    await db.commit()

    await ws_manager.send_to_user(_other_user_id(conversation, current_user.id), {
        "type": "dm_reaction",
        "conversation_id": conversation.id,
        "message_id": message_id,
        "user_id": current_user.id,
        "emoji": body.emoji,
    })
    return {"status": "success", "emoji": body.emoji}


@router.delete("/{message_id}/react")
async def remove_reaction(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Remove the current user's reaction from a message."""
    message, conversation = await _load_message_for_participant(db, message_id, current_user.id)

    result = await db.execute(
        select(DirectMessageReaction).where(
            DirectMessageReaction.message_id == message_id,
            DirectMessageReaction.user_id == current_user.id
        )
    )
    reaction = result.scalar_one_or_none()
    if reaction:
        await db.delete(reaction)
        await db.commit()

    await ws_manager.send_to_user(_other_user_id(conversation, current_user.id), {
        "type": "dm_reaction",
        "conversation_id": conversation.id,
        "message_id": message_id,
        "user_id": current_user.id,
        "emoji": None,
    })
    return {"status": "success"}


# ---------------------------------------------------------------------------
# Unsend
# ---------------------------------------------------------------------------

@router.post("/{message_id}/unsend")
async def unsend_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Unsend (soft-delete) a message. Only the sender may unsend."""
    message, conversation = await _load_message_for_participant(db, message_id, current_user.id)
    if message.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only unsend your own messages")

    if message.deleted_at is None:
        message.deleted_at = datetime.now(timezone.utc)
        await db.commit()

    await ws_manager.send_to_user(_other_user_id(conversation, current_user.id), {
        "type": "dm_unsend",
        "conversation_id": conversation.id,
        "message_id": message_id,
    })
    return {"status": "success"}


# ---------------------------------------------------------------------------
# Read receipts & unread
# ---------------------------------------------------------------------------

class MarkReadRequest(BaseModel):
    up_to_message_id: int


@router.post("/conversations/{conversation_id}/read")
async def mark_read(
    conversation_id: int,
    body: MarkReadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Mark the other user's messages as read and notify them (read receipt)."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation or not _is_participant(conversation, current_user.id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    now = datetime.now(timezone.utc)
    unread_result = await db.execute(
        select(DirectMessage).where(
            DirectMessage.conversation_id == conversation_id,
            DirectMessage.sender_id != current_user.id,
            DirectMessage.read_at.is_(None),
            DirectMessage.id <= body.up_to_message_id
        )
    )
    unread = unread_result.scalars().all()
    for message in unread:
        message.read_at = now
    await db.commit()

    if unread:
        await ws_manager.send_to_user(_other_user_id(conversation, current_user.id), {
            "type": "dm_read",
            "conversation_id": conversation_id,
            "reader_id": current_user.id,
            "up_to_message_id": body.up_to_message_id,
            "read_at": now.isoformat(),
        })

    return {"status": "success", "marked_read": len(unread)}


@router.get("/unread-count")
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Total unread DMs across all conversations (for the tab badge)."""
    result = await db.execute(
        select(func.count(DirectMessage.id))
        .join(Conversation, DirectMessage.conversation_id == Conversation.id)
        .where(
            or_(
                Conversation.user1_id == current_user.id,
                Conversation.user2_id == current_user.id
            ),
            DirectMessage.sender_id != current_user.id,
            DirectMessage.read_at.is_(None),
            DirectMessage.deleted_at.is_(None)
        )
    )
    return {"unread_count": result.scalar() or 0}
