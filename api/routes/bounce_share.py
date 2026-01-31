import secrets
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.database import get_async_session, create_async_session
from db.models import Bounce, BounceInvite, BounceLocationShare, BounceGuestLocation, User
from api.dependencies import get_current_user
from api.routes.websocket import manager
from api.routes.bounces import get_bounce_participants
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

    share_url = f"https://bounce-map.up.railway.app/bounce/share/{bounce.share_token}"
    return {"share_url": share_url, "share_token": bounce.share_token}


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

    # Read the template and inject variables
    import os
    template_path = os.path.join(os.path.dirname(__file__), "..", "..", "templates", "bounce_share.html")
    with open(template_path, "r") as f:
        html = f.read()

    # Replace template placeholders
    html = html.replace("{{VENUE_NAME}}", bounce.venue_name or "")
    html = html.replace("{{VENUE_ADDRESS}}", bounce.venue_address or "")
    html = html.replace("{{LATITUDE}}", str(bounce.latitude))
    html = html.replace("{{LONGITUDE}}", str(bounce.longitude))
    html = html.replace("{{MESSAGE}}", bounce.message or "")
    html = html.replace("{{CREATOR_NAME}}", creator.nickname or creator.first_name or "Someone")
    html = html.replace("{{SHARE_TOKEN}}", share_token)
    html = html.replace("{{GOOGLE_MAPS_API_KEY}}", settings.GOOGLE_MAPS_API_KEY)

    # Derive WS base from the incoming request
    base = str(request.base_url).rstrip("/")
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
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

        # Send initial state
        initial_state = await _build_initial_state(db, bounce_id)
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
            # Mark guest as not sharing on disconnect
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
                    await db.commit()
            except Exception:
                pass

            # Notify everyone that guest left
            try:
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
            "profile_picture": user.profile_picture or user.instagram_profile_pic,
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
