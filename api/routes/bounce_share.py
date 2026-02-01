import secrets
import json
import logging
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.database import get_async_session, create_async_session
from db.models import Bounce, BounceInvite, BounceLocationShare, BounceGuestLocation, User, Follow
from sqlalchemy import func
from api.dependencies import get_current_user
from api.routes.websocket import manager
from api.routes.bounces import get_bounce_participants, get_venue_photo_url
from core.config import settings

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


@router.get("/bounce/share/{share_token}", response_class=HTMLResponse)
async def bounce_share_page(
    share_token: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session)
):
    """Serve the web map page for a shared bounce."""
    result = await db.execute(
        select(Bounce, User)
        .join(User, Bounce.creator_id == User.id)
        .where(Bounce.share_token == share_token, Bounce.status == 'active')
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Bounce not found or no longer active")

    bounce, creator = row

    # Fetch venue photo URL
    venue_photo_url = await get_venue_photo_url(db, bounce.places_fk_id) or ""

    # Creator profile picture
    creator_pic = creator.profile_picture or creator.instagram_profile_pic or creator.profile_picture_1 or ""

    # Read the template and partial sheets
    import os
    tpl_dir = os.path.join(os.path.dirname(__file__), "..", "..", "templates")
    with open(os.path.join(tpl_dir, "bounce_share.html"), "r") as f:
        html = f.read()
    with open(os.path.join(tpl_dir, "venue_sheet.html"), "r") as f:
        html = html.replace("{{VENUE_SHEET}}", f.read())
    with open(os.path.join(tpl_dir, "user_sheet.html"), "r") as f:
        html = html.replace("{{USER_SHEET}}", f.read())

    # Replace template placeholders
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

    # Derive WS base — respect X-Forwarded-Proto (Railway/proxies terminate TLS)
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host") or request.base_url.hostname
    ws_proto = "wss" if proto == "https" else "ws"
    ws_base = f"{ws_proto}://{host}"
    html = html.replace("{{WS_BASE}}", ws_base)

    return HTMLResponse(content=html)


@router.websocket("/ws/bounce/{share_token}")
async def bounce_guest_websocket(
    websocket: WebSocket,
    share_token: str,
    guest_id: str = Query(...),
    name: str = Query(...)
):
    """WebSocket for guest (non-app) users viewing a shared bounce map."""
    db = create_async_session()
    bounce_id = None
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

        await manager.connect_guest(websocket, bounce_id)
        logger.info(f"Guest '{name}' ({guest_id}) connected to bounce {bounce_id}")

        # Upsert guest record on connect (so they show in attendee list even without location)
        result = await db.execute(
            select(BounceGuestLocation).where(
                BounceGuestLocation.bounce_id == bounce_id,
                BounceGuestLocation.guest_id == guest_id
            )
        )
        guest_rec = result.scalar_one_or_none()
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

        # Notify app users that a guest joined
        join_msg = {
            "type": "guest_joined",
            "bounce_id": bounce_id,
            "guest_id": guest_id,
            "display_name": name
        }
        participants = await get_bounce_participants(db, bounce_id)
        for pid in participants:
            await manager.send_to_user(pid, join_msg)

        # Send initial state
        initial_state = await _build_initial_state(db, bounce_id)
        logger.info(f"Sending initial_state to guest '{name}': {len(initial_state.get('app_users', []))} app users, {len(initial_state.get('guests', []))} guests")
        await websocket.send_json(initial_state)

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

            if msg_type == "guest_location":
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

                # Build message
                loc_msg = {
                    "type": "guest_location_shared",
                    "bounce_id": bounce_id,
                    "guest_id": guest_id,
                    "display_name": name,
                    "latitude": lat,
                    "longitude": lng
                }

                # Notify other guest web clients
                await manager.send_to_bounce(bounce_id, loc_msg)

                # Notify app users
                participants = await get_bounce_participants(db, bounce_id)
                for pid in participants:
                    await manager.send_to_user(pid, loc_msg)

            elif msg_type == "guest_stop_sharing":
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

    except WebSocketDisconnect:
        logger.info(f"Guest '{name}' ({guest_id}) disconnected from bounce {bounce_id}")
    except Exception as e:
        logger.error(f"Guest WS error for bounce: {e}")
    finally:
        if bounce_id is not None:
            # Mark guest as disconnected and not sharing
            try:
                result = await db.execute(
                    select(BounceGuestLocation).where(
                        BounceGuestLocation.bounce_id == bounce_id,
                        BounceGuestLocation.guest_id == guest_id
                    )
                )
                guest_loc = result.scalar_one_or_none()
                if guest_loc:
                    guest_loc.is_sharing = False
                    guest_loc.is_connected = False
                    await db.commit()
            except Exception:
                pass

            # Notify everyone that guest left
            try:
                left_msg = {
                    "type": "guest_left",
                    "bounce_id": bounce_id,
                    "guest_id": guest_id
                }
                await manager.send_to_bounce(bounce_id, left_msg)
                participants = await get_bounce_participants(db, bounce_id)
                for pid in participants:
                    await manager.send_to_user(pid, left_msg)
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
