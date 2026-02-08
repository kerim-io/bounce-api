import secrets
import json
import logging
import hashlib
import time
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError
from typing import Optional

from db.database import get_async_session, create_async_session
from db.models import Bounce, BounceInvite, BounceLocationShare, BounceGuestLocation, User, Follow
from sqlalchemy import func
from api.dependencies import get_current_user
from api.routes.websocket import manager
from api.routes.bounces import get_bounce_participants, get_venue_photo_url
from core.config import settings
from services.auth_service import decode_access_token
from services.ai_commentator import get_or_create_commentator, remove_commentator

router = APIRouter(tags=["bounce-share"])
logger = logging.getLogger(__name__)


async def _is_participant(db: AsyncSession, bounce_id: int, user_id: int) -> bool:
    """Check if user is creator or invited to bounce"""
    result = await db.execute(
        select(Bounce).where(Bounce.id == bounce_id, Bounce.creator_id == user_id)
    )
    if result.scalar_one_or_none():
        return True
    result = await db.execute(
        select(BounceInvite).where(
            BounceInvite.bounce_id == bounce_id,
            BounceInvite.user_id == user_id
        )
    )
    return result.scalar_one_or_none() is not None


@router.post("/bounces/{bounce_id}/share-link")
async def create_share_link(
    bounce_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """Generate a shareable link for a bounce. Caller must be a participant."""
    if not await _is_participant(db, bounce_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a participant of this bounce")

    result = await db.execute(
        select(Bounce).where(Bounce.id == bounce_id, Bounce.status == 'active')
    )
    bounce = result.scalar_one_or_none()
    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found or not active")

    if not bounce.share_token:
        bounce.share_token = secrets.token_hex(16)
        await db.commit()
        await db.refresh(bounce)

    # Derive base URL from the incoming request so it works on any domain
    base = str(request.base_url).rstrip("/")
    share_url = f"{base}/bounce/share/{bounce.share_token}"
    return {"share_url": share_url, "share_token": bounce.share_token}


@router.get("/bounce/img-proxy")
async def image_proxy(url: str = Query(...)):
    """Proxy external images to avoid CORS/CORP blocks (e.g. Instagram CDN)."""
    import httpx
    if not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Only HTTPS URLs allowed")
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Upstream error")
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(
                content=resp.content,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"}
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream timeout")
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch image")


@router.get("/bounce/share/{share_token}/attendees")
async def bounce_share_attendees(
    share_token: str,
    db: AsyncSession = Depends(get_async_session)
):
    """Return all attendees for a shared bounce: creator, invited users, and connected guests."""
    result = await db.execute(
        select(Bounce).where(Bounce.share_token == share_token, Bounce.status == 'active')
    )
    bounce = result.scalar_one_or_none()
    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found or inactive")

    # Creator
    result = await db.execute(select(User).where(User.id == bounce.creator_id))
    creator = result.scalar_one_or_none()

    attendees = []
    if creator:
        pic = creator.profile_picture or creator.instagram_profile_pic or creator.profile_picture_1 or ""
        attendees.append({
            "type": "app",
            "user_id": creator.id,
            "nickname": creator.nickname or creator.first_name or "User",
            "profile_picture": pic,
            "is_creator": True,
        })

    # Invited users
    result = await db.execute(
        select(BounceInvite, User)
        .join(User, BounceInvite.user_id == User.id)
        .where(BounceInvite.bounce_id == bounce.id)
    )
    for invite, user in result.all():
        if user.id == bounce.creator_id:
            continue
        pic = user.profile_picture or user.instagram_profile_pic or user.profile_picture_1 or ""
        attendees.append({
            "type": "app",
            "user_id": user.id,
            "nickname": user.nickname or user.first_name or "User",
            "profile_picture": pic,
            "is_creator": False,
        })

    # Connected guests (ever joined via share link for this bounce)
    result = await db.execute(
        select(BounceGuestLocation).where(BounceGuestLocation.bounce_id == bounce.id)
    )
    for guest in result.scalars().all():
        attendees.append({
            "type": "guest",
            "guest_id": guest.guest_id,
            "nickname": guest.display_name or "Guest",
            "is_connected": guest.is_connected,
        })

    return {"attendees": attendees}


@router.get("/bounce/share/{share_token}/user/{user_id}")
async def bounce_share_user_profile(
    share_token: str,
    user_id: int,
    db: AsyncSession = Depends(get_async_session)
):
    """Public profile info for a user visible on the shared bounce map."""
    result = await db.execute(
        select(Bounce).where(Bounce.share_token == share_token, Bounce.status == 'active')
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Bounce not found or inactive")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    followers_count = (await db.execute(
        select(func.count()).select_from(Follow).where(Follow.following_id == user_id)
    )).scalar() or 0
    following_count = (await db.execute(
        select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
    )).scalar() or 0

    pic = user.profile_picture or user.instagram_profile_pic or user.profile_picture_1 or ""
    return {
        "user_id": user.id,
        "nickname": user.nickname or user.first_name or "User",
        "profile_picture": pic,
        "followers_count": followers_count,
        "following_count": following_count,
    }


async def _validate_app_token(db: AsyncSession, token: str, bounce_id: int) -> Optional[User]:
    """Validate a JWT app_token and return the User if they're a participant of this bounce."""
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub"))
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            return None
        if not await _is_participant(db, bounce_id, user.id):
            return None
        return user
    except (JWTError, ValueError, TypeError):
        return None


@router.get("/bounce/chat/{bounce_id}", response_class=HTMLResponse)
async def bounce_chat_page(
    bounce_id: int,
    request: Request,
    app_token: str = Query(...),
    db: AsyncSession = Depends(get_async_session),
):
    """Direct chat page for authenticated app users — no share token needed.

    The app user's JWT is validated and the bounce's share_token is auto-created
    if it doesn't exist. Serves the same map+chat HTML but in app-user mode.
    """
    # Validate JWT
    try:
        payload = decode_access_token(app_token)
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    app_user = result.scalar_one_or_none()
    if not app_user or not app_user.is_active:
        raise HTTPException(status_code=401, detail="Invalid user")

    if not await _is_participant(db, bounce_id, user_id):
        raise HTTPException(status_code=403, detail="Not a participant of this bounce")

    # Load bounce
    result = await db.execute(
        select(Bounce, User)
        .join(User, Bounce.creator_id == User.id)
        .where(Bounce.id == bounce_id, Bounce.status == 'active')
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Bounce not found or not active")

    bounce, creator = row

    # Auto-create share_token if missing (needed for WebSocket endpoint)
    if not bounce.share_token:
        bounce.share_token = secrets.token_hex(16)
        await db.commit()
        await db.refresh(bounce)

    share_token = bounce.share_token

    # Render HTML with app-user identity baked in
    return await _render_bounce_html(
        db, request, bounce, creator, share_token, app_token=app_token, app_user=app_user
    )


async def _render_bounce_html(
    db: AsyncSession,
    request: Request,
    bounce,
    creator,
    share_token: str,
    app_token: Optional[str] = None,
    app_user: Optional[User] = None,
) -> HTMLResponse:
    """Shared HTML renderer for both the guest share page and the app-user chat page."""
    import os

    venue_photo_url = await get_venue_photo_url(db, bounce.places_fk_id) or ""
    creator_pic = creator.profile_picture or creator.instagram_profile_pic or creator.profile_picture_1 or ""

    tpl_dir = os.path.join(os.path.dirname(__file__), "..", "..", "templates")
    with open(os.path.join(tpl_dir, "bounce_share.html"), "r") as f:
        html = f.read()
    with open(os.path.join(tpl_dir, "venue_sheet.html"), "r") as f:
        html = html.replace("{{VENUE_SHEET}}", f.read())
    with open(os.path.join(tpl_dir, "user_sheet.html"), "r") as f:
        html = html.replace("{{USER_SHEET}}", f.read())
    with open(os.path.join(tpl_dir, "feed_item.html"), "r") as f:
        feed_item_html = f.read()
    with open(os.path.join(tpl_dir, "chat_panel.html"), "r") as f:
        chat_panel_html = f.read().replace("{{FEED_ITEM}}", feed_item_html)
    html = html.replace("{{CHAT_PANEL}}", chat_panel_html)

    html = html.replace("{{VENUE_NAME}}", bounce.venue_name or "")
    html = html.replace("{{VENUE_ADDRESS}}", bounce.venue_address or "")
    html = html.replace("{{LATITUDE}}", str(bounce.latitude))
    html = html.replace("{{LONGITUDE}}", str(bounce.longitude))
    html = html.replace("{{MESSAGE}}", bounce.message or "")
    html = html.replace("{{CREATOR_NAME}}", creator.nickname or creator.first_name or "Someone")
    html = html.replace("{{SHARE_TOKEN}}", share_token)
    html = html.replace("{{VENUE_PHOTO_URL}}", venue_photo_url)
    html = html.replace("{{CREATOR_PROFILE_PIC}}", creator_pic)
    html = html.replace("{{GOOGLE_MAPS_API_KEY}}", settings.GOOGLE_MAPS_API_KEY)

    if app_user and app_token:
        app_user_pic = app_user.profile_picture or app_user.instagram_profile_pic or app_user.profile_picture_1 or ""
        app_user_name = app_user.nickname or app_user.first_name or "User"
        html = html.replace("{{IS_APP_USER}}", "true")
        html = html.replace("{{APP_USER_ID}}", str(app_user.id))
        html = html.replace("{{APP_USER_NAME}}", app_user_name)
        html = html.replace("{{APP_USER_PIC}}", app_user_pic)
        html = html.replace("{{APP_TOKEN}}", app_token)
    else:
        html = html.replace("{{IS_APP_USER}}", "false")
        html = html.replace("{{APP_USER_ID}}", "0")
        html = html.replace("{{APP_USER_NAME}}", "")
        html = html.replace("{{APP_USER_PIC}}", "")
        html = html.replace("{{APP_TOKEN}}", "")

    bounce_time_iso = bounce.bounce_time.isoformat() if bounce.bounce_time else ""
    html = html.replace("{{BOUNCE_TIME}}", bounce_time_iso)
    html = html.replace("{{IS_NOW}}", "true" if bounce.is_now else "false")

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host") or request.base_url.hostname
    ws_proto = "wss" if proto == "https" else "ws"
    ws_base = f"{ws_proto}://{host}"
    html = html.replace("{{WS_BASE}}", ws_base)

    return HTMLResponse(content=html)


@router.get("/bounce/share/{share_token}", response_class=HTMLResponse)
async def bounce_share_page(
    share_token: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    app_token: Optional[str] = Query(None),
):
    """Serve the web map page for a shared bounce (guest link)."""
    result = await db.execute(
        select(Bounce, User)
        .join(User, Bounce.creator_id == User.id)
        .where(Bounce.share_token == share_token, Bounce.status == 'active')
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Bounce not found or no longer active")

    bounce, creator = row

    app_user: Optional[User] = None
    if app_token:
        app_user = await _validate_app_token(db, app_token, bounce.id)

    return await _render_bounce_html(
        db, request, bounce, creator, share_token,
        app_token=app_token, app_user=app_user,
    )


@router.websocket("/ws/bounce/{share_token}")
async def bounce_guest_websocket(
    websocket: WebSocket,
    share_token: str,
    guest_id: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    app_token: Optional[str] = Query(None),
):
    """WebSocket for users viewing a shared bounce map.

    Guest mode (default):  ?guest_id=<uuid>&name=<display_name>
    App-user mode:         ?app_token=<jwt>   (no guest record created)
    """
    db = create_async_session()
    bounce_id = None
    explicit_leave = False
    is_app_user = False
    app_user_id: Optional[int] = None

    try:
        # Validate share_token
        result = await db.execute(
            select(Bounce).where(Bounce.share_token == share_token, Bounce.status == 'active')
        )
        bounce = result.scalar_one_or_none()
        if not bounce:
            await websocket.close(code=4004, reason="Bounce not found or inactive")
            return

        bounce_id = bounce.id

        # Determine if this is an app user or guest
        if app_token:
            app_user = await _validate_app_token(db, app_token, bounce.id)
            if not app_user:
                await websocket.close(code=4001, reason="Invalid app token or not a participant")
                return
            is_app_user = True
            app_user_id = app_user.id
            name = app_user.nickname or app_user.first_name or "User"
            guest_id = f"app_{app_user.id}"  # synthetic ID for commentator tracking
            profile_pic = app_user.profile_picture or app_user.instagram_profile_pic or app_user.profile_picture_1 or ""
            logger.info(f"App user '{name}' (id={app_user_id}) connected to bounce chat {bounce_id}")
        else:
            if not guest_id or not name:
                await websocket.close(code=4000, reason="guest_id and name are required")
                return

        await manager.connect_guest(websocket, bounce_id)

        if not is_app_user:
            logger.info(f"Guest '{name}' ({guest_id}) connected to bounce {bounce_id}")

            # Check if this guest already exists (reconnect vs first join)
            result = await db.execute(
                select(BounceGuestLocation).where(
                    BounceGuestLocation.bounce_id == bounce_id,
                    BounceGuestLocation.guest_id == guest_id
                )
            )
            guest_rec = result.scalar_one_or_none()
            is_new_guest = guest_rec is None

            if guest_rec:
                guest_rec.display_name = name
                guest_rec.is_connected = True
            else:
                guest_rec = BounceGuestLocation(
                    bounce_id=bounce_id,
                    guest_id=guest_id,
                    display_name=name,
                    latitude=0,
                    longitude=0,
                    is_sharing=False,
                    is_connected=True
                )
                db.add(guest_rec)
            await db.commit()

            # Only notify on FIRST join, not on reconnect/refresh
            if is_new_guest:
                join_msg = {
                    "type": "guest_joined",
                    "bounce_id": bounce_id,
                    "guest_id": guest_id,
                    "display_name": name
                }
                await manager.send_to_bounce(bounce_id, join_msg)
                participants = await get_bounce_participants(db, bounce_id)
                for pid in participants:
                    await manager.send_to_user(pid, join_msg)

                # Send push notification to app participants
                from services.apns_service import NotificationPayload, NotificationType
                from services.tasks import enqueue_notification, payload_to_dict
                for pid in participants:
                    payload = NotificationPayload(
                        notification_type=NotificationType.GUEST_JOINED,
                        title="Guest Joined",
                        body=f"{name} joined the bounce at {bounce.venue_name}",
                        actor_id=0,
                        actor_nickname=name,
                        bounce_id=bounce.id,
                        bounce_venue_name=bounce.venue_name,
                        bounce_place_id=bounce.place_id
                    )
                    enqueue_notification(pid, payload_to_dict(payload))

        # Send initial state
        initial_state = await _build_initial_state(db, bounce_id)
        logger.info(f"Sending initial_state to '{name}': {len(initial_state.get('app_users', []))} app users, {len(initial_state.get('guests', []))} guests")
        await websocket.send_json(initial_state)

        # Fetch creator name for commentator context
        creator_result = await db.execute(
            select(User).where(User.id == bounce.creator_id)
        )
        creator_user = creator_result.scalar_one_or_none()
        creator_name = (creator_user.nickname or creator_user.first_name or "the host") if creator_user else "the host"

        # Init AI commentator
        commentator = get_or_create_commentator(
            bounce_id,
            {
                "venue_name": bounce.venue_name or "the venue",
                "venue_address": bounce.venue_address or "",
                "latitude": bounce.latitude,
                "longitude": bounce.longitude,
                "message": bounce.message or "",
                "creator_name": creator_name,
            },
            manager.send_to_bounce,
        )
        commentator.attendees[guest_id] = {
            "name": name, "last_lat": 0, "last_lng": 0, "last_seen": time.time()
        }

        # Send chat history to late joiner
        history = commentator.get_history()
        if history:
            await websocket.send_json({"type": "chat_history", "messages": history})

        # Notify AI about the join (skip for app users — they're already attendees)
        if not is_app_user:
            commentator.push_event({"type": "join", "name": name})

        # Message loop
        while True:
            raw = await websocket.receive_text()

            if raw == "ping":
                await websocket.send_text("pong")
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            if msg_type == "guest_location" and not is_app_user:
                lat = data.get("latitude")
                lng = data.get("longitude")
                if lat is None or lng is None:
                    continue

                # Upsert guest location
                result = await db.execute(
                    select(BounceGuestLocation).where(
                        BounceGuestLocation.bounce_id == bounce_id,
                        BounceGuestLocation.guest_id == guest_id
                    )
                )
                guest_loc = result.scalar_one_or_none()
                if guest_loc:
                    guest_loc.latitude = lat
                    guest_loc.longitude = lng
                    guest_loc.is_sharing = True
                    guest_loc.display_name = name
                else:
                    guest_loc = BounceGuestLocation(
                        bounce_id=bounce_id,
                        guest_id=guest_id,
                        display_name=name,
                        latitude=lat,
                        longitude=lng,
                        is_sharing=True
                    )
                    db.add(guest_loc)
                await db.commit()

                loc_msg = {
                    "type": "guest_location_shared",
                    "bounce_id": bounce_id,
                    "guest_id": guest_id,
                    "display_name": name,
                    "latitude": lat,
                    "longitude": lng
                }

                await manager.send_to_bounce(bounce_id, loc_msg)
                participants = await get_bounce_participants(db, bounce_id)
                for pid in participants:
                    await manager.send_to_user(pid, loc_msg)

                commentator.check_arrival(guest_id, name, lat, lng)

            elif msg_type == "guest_stop_sharing" and not is_app_user:
                result = await db.execute(
                    select(BounceGuestLocation).where(
                        BounceGuestLocation.bounce_id == bounce_id,
                        BounceGuestLocation.guest_id == guest_id
                    )
                )
                guest_loc = result.scalar_one_or_none()
                if guest_loc:
                    guest_loc.is_sharing = False
                    await db.commit()

                stop_msg = {
                    "type": "guest_location_stopped",
                    "bounce_id": bounce_id,
                    "guest_id": guest_id
                }
                await manager.send_to_bounce(bounce_id, stop_msg)
                participants = await get_bounce_participants(db, bounce_id)
                for pid in participants:
                    await manager.send_to_user(pid, stop_msg)

            elif msg_type == "chat_message":
                text = (data.get("text") or "").strip()
                if not text or len(text) > 500:
                    continue

                chat_msg = {
                    "type": "chat_message",
                    "sender": name,
                    "text": text,
                    "is_ai": False,
                    "timestamp": time.time(),
                }
                # Tag with user_id for app users, guest_id for guests
                if is_app_user:
                    chat_msg["user_id"] = app_user_id
                    chat_msg["profile_picture"] = profile_pic
                else:
                    chat_msg["guest_id"] = guest_id

                commentator.add_chat(name, text, is_ai=False)
                await manager.send_to_bounce(bounce_id, chat_msg)
                commentator.push_event({"type": "chat", "sender": name, "text": text})

            elif msg_type == "guest_leave" and not is_app_user:
                explicit_leave = True
                break

    except WebSocketDisconnect:
        logger.info(f"'{name}' ({guest_id}) disconnected from bounce {bounce_id}")
    except Exception as e:
        logger.error(f"Guest WS error for bounce: {e}")
    finally:
        if bounce_id is not None:
            # App users don't have guest records — skip guest cleanup
            if not is_app_user:
                try:
                    result = await db.execute(
                        select(BounceGuestLocation).where(
                            BounceGuestLocation.bounce_id == bounce_id,
                            BounceGuestLocation.guest_id == guest_id
                        )
                    )
                    guest_loc = result.scalar_one_or_none()

                    if explicit_leave and guest_loc:
                        await db.delete(guest_loc)
                        await db.commit()
                    elif guest_loc:
                        guest_loc.is_sharing = False
                        guest_loc.is_connected = True
                        await db.commit()
                except Exception:
                    pass

                try:
                    if explicit_leave:
                        notify_msg = {
                            "type": "guest_left",
                            "bounce_id": bounce_id,
                            "guest_id": guest_id,
                            "display_name": name
                        }
                        await manager.send_to_bounce(bounce_id, notify_msg)
                        participants = await get_bounce_participants(db, bounce_id)
                        for pid in participants:
                            await manager.send_to_user(pid, notify_msg)
                    else:
                        stop_msg = {
                            "type": "guest_location_stopped",
                            "bounce_id": bounce_id,
                            "guest_id": guest_id
                        }
                        await manager.send_to_bounce(bounce_id, stop_msg)
                        participants = await get_bounce_participants(db, bounce_id)
                        for pid in participants:
                            await manager.send_to_user(pid, stop_msg)
                except Exception:
                    pass

            # Clean up commentator tracking
            try:
                from services.ai_commentator import _commentators
                if bounce_id in _commentators:
                    c = _commentators[bounce_id]
                    c.attendees.pop(guest_id, None)
                    if not is_app_user:
                        c.push_event({"type": "leave", "name": name})
                    if not c.attendees:
                        await remove_commentator(bounce_id)
            except Exception:
                pass

            manager.disconnect_guest(websocket, bounce_id)
        await db.close()


async def _build_initial_state(db: AsyncSession, bounce_id: int) -> dict:
    """Build the initial_state message with all current locations."""
    # App user locations
    result = await db.execute(
        select(BounceLocationShare, User)
        .join(User, BounceLocationShare.user_id == User.id)
        .where(
            BounceLocationShare.bounce_id == bounce_id,
            BounceLocationShare.is_sharing == True,
            BounceLocationShare.latitude != 0
        )
    )
    app_users = []
    for share, user in result.all():
        app_users.append({
            "user_id": share.user_id,
            "nickname": user.nickname,
            "profile_picture": user.profile_picture or user.instagram_profile_pic or user.profile_picture_1,
            "latitude": share.latitude,
            "longitude": share.longitude
        })

    # Guest locations
    result = await db.execute(
        select(BounceGuestLocation).where(
            BounceGuestLocation.bounce_id == bounce_id,
            BounceGuestLocation.is_sharing == True
        )
    )
    guests = []
    for guest in result.scalars().all():
        guests.append({
            "guest_id": guest.guest_id,
            "display_name": guest.display_name,
            "latitude": guest.latitude,
            "longitude": guest.longitude
        })

    return {
        "type": "initial_state",
        "bounce_id": bounce_id,
        "app_users": app_users,
        "guests": guests
    }
