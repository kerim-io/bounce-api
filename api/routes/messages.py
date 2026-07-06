from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import logging

from db.database import get_async_session
from db.models import User, Conversation, DirectMessage
from api.dependencies import get_current_user
from api.routes.websocket import manager as ws_manager
from services.tasks import enqueue_notification, payload_to_dict

router = APIRouter(prefix="/messages", tags=["messages"])
logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 2000


class SendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)
    client_id: Optional[str] = Field(None, max_length=64)  # UUID for optimistic-send dedupe


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    text: str
    client_id: Optional[str]
    created_at: datetime
    read_at: Optional[datetime]


class ConversationUser(BaseModel):
    id: int
    nickname: Optional[str]
    first_name: Optional[str]
    profile_picture: Optional[str]


class ConversationResponse(BaseModel):
    conversation_id: int
    other_user: ConversationUser
    last_message: Optional[MessageResponse]
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


def _message_dict(message: DirectMessage) -> dict:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "text": message.text,
        "client_id": message.client_id,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "read_at": message.read_at.isoformat() if message.read_at else None,
    }


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

    # Last message per conversation
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

    # Unread counts (messages from the other user I haven't read)
    unread_result = await db.execute(
        select(DirectMessage.conversation_id, func.count(DirectMessage.id))
        .where(
            DirectMessage.conversation_id.in_(conversation_ids),
            DirectMessage.sender_id != current_user.id,
            DirectMessage.read_at.is_(None)
        )
        .group_by(DirectMessage.conversation_id)
    )
    unread_counts = dict(unread_result.all())

    # Other users, one query
    other_ids = [_other_user_id(c, current_user.id) for c in conversations]
    users_result = await db.execute(select(User).where(User.id.in_(other_ids)))
    users = {u.id: u for u in users_result.scalars().all()}

    out = []
    for conversation in conversations:
        other = users.get(_other_user_id(conversation, current_user.id))
        if not other:
            continue
        last = last_messages.get(conversation.id)
        out.append(ConversationResponse(
            conversation_id=conversation.id,
            other_user=ConversationUser(
                id=other.id,
                nickname=other.nickname,
                first_name=other.first_name,
                profile_picture=other.profile_picture or other.instagram_profile_pic,
            ),
            last_message=MessageResponse(
                id=last.id,
                conversation_id=last.conversation_id,
                sender_id=last.sender_id,
                text=last.text,
                client_id=last.client_id,
                created_at=last.created_at,
                read_at=last.read_at,
            ) if last else None,
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
    """
    Message history with a user, newest first (paginate with before_id).
    Doesn't create a conversation — returns empty until the first message.
    """
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
        "messages": [_message_dict(m) for m in messages],
    }


@router.post("/to/{user_id}", response_model=MessageResponse)
async def send_message(
    user_id: int,
    body: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Send a DM: persists, pushes over WebSocket, and sends an APNs notification."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot message yourself")

    recipient_result = await db.execute(select(User).where(User.id == user_id))
    recipient = recipient_result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(status_code=404, detail="User not found")

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message is empty")

    conversation = await _get_or_create_conversation(db, current_user.id, user_id)

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
            return MessageResponse(
                id=existing.id,
                conversation_id=existing.conversation_id,
                sender_id=existing.sender_id,
                text=existing.text,
                client_id=existing.client_id,
                created_at=existing.created_at,
                read_at=existing.read_at,
            )

    message = DirectMessage(
        conversation_id=conversation.id,
        sender_id=current_user.id,
        text=text,
        client_id=body.client_id,
    )
    db.add(message)
    conversation.last_message_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(message)

    sender_name = current_user.nickname or current_user.first_name or "Someone"
    sender_pic = current_user.profile_picture or current_user.instagram_profile_pic

    # Realtime delivery to the recipient (all their devices/instances)
    await ws_manager.send_to_user(user_id, {
        "type": "dm",
        "message": _message_dict(message),
        "sender": {
            "id": current_user.id,
            "nickname": current_user.nickname,
            "first_name": current_user.first_name,
            "profile_picture": sender_pic,
        },
    })

    # Push notification (deep-links into the chat via conversation_id)
    from services.apns_service import NotificationPayload, NotificationType
    payload = NotificationPayload(
        notification_type=NotificationType.MESSAGE,
        title=sender_name,
        body=text if len(text) <= 120 else text[:117] + "...",
        actor_id=current_user.id,
        actor_nickname=sender_name,
        actor_profile_picture=sender_pic,
        conversation_id=conversation.id,
    )
    enqueue_notification(user_id, payload_to_dict(payload))

    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_id=message.sender_id,
        text=message.text,
        client_id=message.client_id,
        created_at=message.created_at,
        read_at=message.read_at,
    )


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
    if not conversation or current_user.id not in (conversation.user1_id, conversation.user2_id):
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
            DirectMessage.read_at.is_(None)
        )
    )
    return {"unread_count": result.scalar() or 0}
