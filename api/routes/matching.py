"""Social matching endpoints.

GET /matching/people?place_id=      who at this venue you'd click with (%)
GET /matching/venues-now?lat=&lng=  where to head right now
GET /matching/me/profile            your agent's dossier (transparency)

Surfacing note: check-ins are already public in this app (venue attendee
lists, live check-in broadcasts), so ranking currently-present people does
not reveal anything the venue card doesn't.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.routes.checkins import CHECKIN_EXPIRY_HOURS
from db.database import get_async_session
from db.models import CheckIn, User
from services.matching import (
    get_active_occupants,
    get_matching_model,
    get_place_meta,
    rank_people,
    rank_venues_now,
)
from services.profile_agent import get_persona, refresh_user_profile

router = APIRouter(prefix="/matching", tags=["matching"])
logger = logging.getLogger(__name__)


async def _current_place(db: AsyncSession, user_id: int) -> Optional[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CHECKIN_EXPIRY_HOURS)
    row = (await db.execute(
        select(CheckIn.place_id).where(
            CheckIn.user_id == user_id,
            CheckIn.is_active == True,  # noqa: E712
            CheckIn.last_seen_at >= cutoff,
        ).limit(1)
    )).scalar_one_or_none()
    return row


def _agent_candidates(model, user_id: int, names: dict[int, str]) -> list[dict]:
    """Co-presence partners the user hasn't followed — the agent picks from these."""
    partners = model.copresence_partners.get(user_id, {})
    already = model.following.get(user_id, set())
    ranked = sorted(
        ((n, uid) for uid, n in partners.items() if uid not in already and uid != user_id),
        reverse=True,
    )
    return [
        {"user_id": uid, "label": f"{names.get(uid, 'user')} — crossed paths {n}x"}
        for n, uid in ranked[:8]
    ]


@router.get("/people")
async def people_here(
    place_id: Optional[str] = Query(None, description="Defaults to your current check-in"),
    limit: int = Query(10, ge=1, le=25),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """People checked in at the venue right now, ranked by match probability."""
    target = place_id or await _current_place(db, current_user.id)
    if not target:
        raise HTTPException(status_code=400, detail="Not checked in anywhere — pass place_id")

    model = await get_matching_model(db)
    occupants = await get_active_occupants(db, CHECKIN_EXPIRY_HOURS)
    candidates = [u for u in occupants.get(target, []) if u != current_user.id]
    ranked = rank_people(model, current_user.id, candidates)[:limit]

    users = {}
    if ranked:
        rows = (await db.execute(
            select(User).where(User.id.in_([r["user_id"] for r in ranked]))
        )).scalars().all()
        users = {u.id: u for u in rows}

    people = []
    for r in ranked:
        u = users.get(r["user_id"])
        if not u:
            continue
        people.append({
            "user_id": u.id,
            "nickname": u.nickname or u.first_name or "Someone",
            "profile_picture": f"/img/user/{u.id}",
            "match_pct": round(r["match_probability"] * 100, 1),
            "p_you_to_them": r["p_i_to_j"],
            "p_them_to_you": r["p_j_to_i"],
            "uncertain": r["uncertain"],
            "reasons": r["reasons"],
        })

    # Keep the agents warm for everyone we just looked at (fire-and-forget)
    names = {u.id: (u.nickname or u.first_name or "user") for u in users.values()}
    asyncio.create_task(refresh_user_profile(
        current_user.id,
        candidate_people=_agent_candidates(model, current_user.id, names),
    ))

    return {"place_id": target, "people": people}


@router.get("/venues-now")
async def venues_now(
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    limit: int = Query(5, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Where to head right now, scored by expected promising encounters."""
    model = await get_matching_model(db)
    occupants = await get_active_occupants(db, CHECKIN_EXPIRY_HOURS)
    if not occupants:
        return {"venues": []}

    here = await _current_place(db, current_user.id)
    meta = await get_place_meta(db, list(occupants.keys()))
    venues = rank_venues_now(
        model, current_user.id, occupants, meta,
        lat=lat, lng=lng, exclude_place=here, limit=limit,
    )

    # attach names to top people
    top_ids = [p["user_id"] for v in venues for p in v["top_people"]]
    names = {}
    if top_ids:
        rows = (await db.execute(select(User).where(User.id.in_(top_ids)))).scalars().all()
        names = {u.id: (u.nickname or u.first_name or "Someone") for u in rows}
    for v in venues:
        for p in v["top_people"]:
            p["nickname"] = names.get(p["user_id"])
            p["profile_picture"] = f"/img/user/{p['user_id']}"
            p["match_pct"] = round(p.pop("match_probability") * 100, 1)

    return {"venues": venues}


@router.get("/me/profile")
async def my_agent_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """What your agent has written about you (transparency + debugging)."""
    profile = await get_persona(db, current_user.id)
    if not profile:
        asyncio.create_task(refresh_user_profile(current_user.id, force=True))
        return {"status": "building", "profile": None}
    return {"status": "ready", "profile": profile}
