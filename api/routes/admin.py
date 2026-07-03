from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime, timezone

from db.database import get_async_session
from db.models import User, CheckIn, Bounce, BounceInvite, BounceAttendee, Follow, Place, CheckInHistory
from api.dependencies import get_admin_user
from services.auth_service import create_access_token
from services.redis import get_redis
from core.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")


# ============================================================================
# LOGIN / LOGOUT
# ============================================================================

@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Render admin login page."""
    return templates.TemplateResponse("admin/login.html", {"request": request})


@router.post("/login")
async def admin_login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_async_session)
):
    """Process admin login."""
    # Look up user by email
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # For security, use a simple password check (in production, use proper hashing)
    # The password should be the user's apple_user_id for now (as a simple auth)
    if not user or not user.is_admin:
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Invalid credentials or not an admin"},
            status_code=401
        )

    # Check password (using apple_user_id as password for simplicity)
    if password != user.apple_user_id:
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=401
        )

    # Create JWT token
    token = create_access_token(data={"sub": str(user.id)})

    # Set cookie and redirect to dashboard
    response = RedirectResponse(url="/admin/", status_code=302)
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24  # 24 hours
    )
    return response


@router.get("/logout")
async def admin_logout():
    """Logout and clear session cookie."""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie(key="admin_token")
    return response


# ============================================================================
# DASHBOARD
# ============================================================================

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """Admin dashboard with stats overview."""
    # Get counts
    user_count = await db.scalar(select(func.count(User.id)))
    checkin_count = await db.scalar(select(func.count(CheckIn.id)))
    bounce_count = await db.scalar(select(func.count(Bounce.id)))
    place_count = await db.scalar(select(func.count(Place.id)))
    follow_count = await db.scalar(select(func.count(Follow.id)))

    # Active checkins (is_active=True)
    active_checkins = await db.scalar(
        select(func.count(CheckIn.id)).where(CheckIn.is_active == True)
    )

    # Active bounces
    active_bounces = await db.scalar(
        select(func.count(Bounce.id)).where(Bounce.status == 'active')
    )

    # Recent users (last 7 days)
    from datetime import timedelta
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_users = await db.scalar(
        select(func.count(User.id)).where(User.created_at >= week_ago)
    )

    stats = {
        "users": user_count or 0,
        "checkins": checkin_count or 0,
        "bounces": bounce_count or 0,
        "places": place_count or 0,
        "follows": follow_count or 0,
        "active_checkins": active_checkins or 0,
        "active_bounces": active_bounces or 0,
        "recent_users": recent_users or 0
    }

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "admin": admin, "stats": stats}
    )


# ============================================================================
# USERS
# ============================================================================

@router.get("/users", response_class=HTMLResponse)
async def admin_users_list(
    request: Request,
    page: int = 1,
    search: str = "",
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """List all users with pagination and search."""
    per_page = 20
    offset = (page - 1) * per_page

    # Build query
    query = select(User)
    count_query = select(func.count(User.id))

    if search:
        search_filter = (
            User.nickname.ilike(f"%{search}%") |
            User.email.ilike(f"%{search}%") |
            User.first_name.ilike(f"%{search}%") |
            User.last_name.ilike(f"%{search}%")
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    # Get total count
    total = await db.scalar(count_query) or 0
    total_pages = (total + per_page - 1) // per_page

    # Get users
    query = query.order_by(User.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()

    return templates.TemplateResponse(
        "admin/users/list.html",
        {
            "request": request,
            "admin": admin,
            "users": users,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "search": search
        }
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """View user details."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.check_ins))
        .options(selectinload(User.bounces_created))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get follower/following counts
    follower_count = await db.scalar(
        select(func.count(Follow.id)).where(Follow.following_id == user_id)
    )
    following_count = await db.scalar(
        select(func.count(Follow.id)).where(Follow.follower_id == user_id)
    )

    return templates.TemplateResponse(
        "admin/users/detail.html",
        {
            "request": request,
            "admin": admin,
            "user": user,
            "follower_count": follower_count or 0,
            "following_count": following_count or 0
        }
    )


@router.post("/users/{user_id}")
async def admin_user_update(
    request: Request,
    user_id: int,
    nickname: str = Form(None),
    email: str = Form(None),
    is_active: bool = Form(False),
    is_admin: bool = Form(False),
    can_post: bool = Form(False),
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """Update user details."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update fields
    if nickname is not None:
        user.nickname = nickname
    if email is not None:
        user.email = email
    user.is_active = is_active
    user.is_admin = is_admin
    user.can_post = can_post

    await db.commit()

    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/delete")
async def admin_user_delete(
    user_id: int,
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """Delete a user."""
    # Prevent self-deletion
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()

    return RedirectResponse(url="/admin/users", status_code=302)


# ============================================================================
# CHECK-INS
# ============================================================================

@router.get("/checkins", response_class=HTMLResponse)
async def admin_checkins_list(
    request: Request,
    page: int = 1,
    active_only: bool = False,
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """List all check-ins with pagination."""
    per_page = 20
    offset = (page - 1) * per_page

    # Build query
    query = select(CheckIn).options(selectinload(CheckIn.user), selectinload(CheckIn.place))
    count_query = select(func.count(CheckIn.id))

    if active_only:
        query = query.where(CheckIn.is_active == True)
        count_query = count_query.where(CheckIn.is_active == True)

    # Get total count
    total = await db.scalar(count_query) or 0
    total_pages = (total + per_page - 1) // per_page

    # Get check-ins
    query = query.order_by(CheckIn.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    checkins = result.scalars().all()

    return templates.TemplateResponse(
        "admin/checkins/list.html",
        {
            "request": request,
            "admin": admin,
            "checkins": checkins,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "active_only": active_only
        }
    )


@router.post("/checkins/{checkin_id}/delete")
async def admin_checkin_delete(
    checkin_id: int,
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """Delete a check-in."""
    result = await db.execute(select(CheckIn).where(CheckIn.id == checkin_id))
    checkin = result.scalar_one_or_none()

    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")

    await db.delete(checkin)
    await db.commit()

    return RedirectResponse(url="/admin/checkins", status_code=302)


# ============================================================================
# BOUNCES
# ============================================================================

@router.get("/bounces", response_class=HTMLResponse)
async def admin_bounces_list(
    request: Request,
    page: int = 1,
    status_filter: str = "",
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """List all bounces with pagination."""
    per_page = 20
    offset = (page - 1) * per_page

    # Build query
    query = select(Bounce).options(selectinload(Bounce.creator), selectinload(Bounce.invites))
    count_query = select(func.count(Bounce.id))

    if status_filter:
        query = query.where(Bounce.status == status_filter)
        count_query = count_query.where(Bounce.status == status_filter)

    # Get total count
    total = await db.scalar(count_query) or 0
    total_pages = (total + per_page - 1) // per_page

    # Get bounces
    query = query.order_by(Bounce.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    bounces = result.scalars().all()

    return templates.TemplateResponse(
        "admin/bounces/list.html",
        {
            "request": request,
            "admin": admin,
            "bounces": bounces,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "status_filter": status_filter
        }
    )


@router.get("/bounces/{bounce_id}", response_class=HTMLResponse)
async def admin_bounce_detail(
    request: Request,
    bounce_id: int,
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """View bounce details."""
    result = await db.execute(
        select(Bounce)
        .options(selectinload(Bounce.creator))
        .options(selectinload(Bounce.invites).selectinload(BounceInvite.user))
        .options(selectinload(Bounce.attendees).selectinload(BounceAttendee.user))
        .where(Bounce.id == bounce_id)
    )
    bounce = result.scalar_one_or_none()

    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found")

    return templates.TemplateResponse(
        "admin/bounces/detail.html",
        {"request": request, "admin": admin, "bounce": bounce}
    )


@router.post("/bounces/{bounce_id}")
async def admin_bounce_update(
    request: Request,
    bounce_id: int,
    venue_name: str = Form(...),
    status: str = Form(...),
    is_public: bool = Form(False),
    is_now: bool = Form(False),
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """Update bounce details."""
    result = await db.execute(select(Bounce).where(Bounce.id == bounce_id))
    bounce = result.scalar_one_or_none()

    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found")

    bounce.venue_name = venue_name
    bounce.status = status
    bounce.is_public = is_public
    bounce.is_now = is_now

    await db.commit()

    return RedirectResponse(url=f"/admin/bounces/{bounce_id}", status_code=302)


@router.post("/bounces/{bounce_id}/delete")
async def admin_bounce_delete(
    bounce_id: int,
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """Delete a bounce."""
    result = await db.execute(select(Bounce).where(Bounce.id == bounce_id))
    bounce = result.scalar_one_or_none()

    if not bounce:
        raise HTTPException(status_code=404, detail="Bounce not found")

    await db.delete(bounce)
    await db.commit()

    return RedirectResponse(url="/admin/bounces", status_code=302)


# ============================================================================
# PLACES
# ============================================================================

@router.get("/places", response_class=HTMLResponse)
async def admin_places_list(
    request: Request,
    page: int = 1,
    search: str = "",
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """List all places with pagination."""
    per_page = 20
    offset = (page - 1) * per_page

    # Build query
    query = select(Place)
    count_query = select(func.count(Place.id))

    if search:
        search_filter = Place.name.ilike(f"%{search}%") | Place.address.ilike(f"%{search}%")
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    # Get total count
    total = await db.scalar(count_query) or 0
    total_pages = (total + per_page - 1) // per_page

    # Get places
    query = query.order_by(Place.bounce_count.desc(), Place.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    places = result.scalars().all()

    return templates.TemplateResponse(
        "admin/places/list.html",
        {
            "request": request,
            "admin": admin,
            "places": places,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "search": search
        }
    )


# ============================================================================
# FOLLOWS
# ============================================================================

@router.get("/follows", response_class=HTMLResponse)
async def admin_follows_list(
    request: Request,
    page: int = 1,
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """List all follow relationships with pagination."""
    per_page = 20
    offset = (page - 1) * per_page

    # Get total count
    total = await db.scalar(select(func.count(Follow.id))) or 0
    total_pages = (total + per_page - 1) // per_page

    # Get follows with user relationships
    query = (
        select(Follow)
        .options(selectinload(Follow.follower))
        .options(selectinload(Follow.following))
        .order_by(Follow.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(query)
    follows = result.scalars().all()

    return templates.TemplateResponse(
        "admin/follows/list.html",
        {
            "request": request,
            "admin": admin,
            "follows": follows,
            "page": page,
            "total_pages": total_pages,
            "total": total
        }
    )


@router.post("/follows/{follow_id}/delete")
async def admin_follow_delete(
    follow_id: int,
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """Delete a follow relationship."""
    result = await db.execute(select(Follow).where(Follow.id == follow_id))
    follow = result.scalar_one_or_none()

    if not follow:
        raise HTTPException(status_code=404, detail="Follow not found")

    await db.delete(follow)
    await db.commit()

    return RedirectResponse(url="/admin/follows", status_code=302)


# ============================================================================
# USERS MAP (live location)
# ============================================================================

@router.get("/api/users/locations")
async def admin_users_locations(
    db: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    """JSON endpoint: all users with a known location, online status, and venue if checked in."""
    from sqlalchemy.orm import aliased

    # Users that have reported a location at least once
    result = await db.execute(
        select(User).where(User.last_location_lat.isnot(None))
    )
    users = result.scalars().all()

    if not users:
        return []

    # Bulk-fetch active check-ins with venue info
    active_checkins_result = await db.execute(
        select(CheckIn).where(CheckIn.is_active == True)
    )
    active_checkins = {ci.user_id: ci for ci in active_checkins_result.scalars().all()}

    # Bulk-check Redis online flags
    r = await get_redis()
    user_ids = [u.id for u in users]
    keys = [f"user:alive:{uid}" for uid in user_ids]
    alive_values = await r.mget(keys)
    alive_set = {uid for uid, val in zip(user_ids, alive_values) if val}

    out = []
    for u in users:
        ci = active_checkins.get(u.id)
        out.append({
            "id": u.id,
            "nickname": u.nickname,
            "profile_pic": u.profile_picture or u.instagram_profile_pic,
            "latitude": u.last_location_lat,
            "longitude": u.last_location_lon,
            "is_online": u.id in alive_set,
            "last_seen": u.last_location_update.isoformat() if u.last_location_update else None,
            "venue_name": ci.location_name if ci else None,
            "place_id": ci.place_id if ci else None,
        })

    return out


@router.get("/users/map", response_class=HTMLResponse)
async def admin_users_map(
    request: Request,
    admin: User = Depends(get_admin_user)
):
    """Render the live users map page."""
    return templates.TemplateResponse(
        "admin/users/map.html",
        {
            "request": request,
            "admin": admin,
            "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
        }
    )
