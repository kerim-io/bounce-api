"""Per-user LLM profile agents.

Each user gets a tiny agent (one Groq llama-3.1-8b call, refreshed at most
every 3 days or after enough new activity) that reads their behavior log and
writes: a persona sketch, a structured trait vector, and concrete ideas
(people to follow, venues to try) with reasons.

Why an LLM here at all, when the Bayesian layer already does the math:

1. SEMANTIC COLD-START. Matrix factorization can only connect users through
   overlapping venue sets. The agent reads what the math treats as opaque
   IDs — venue names, categories, and hours ("Basement at 1am Thursdays;
   Pace Gallery Saturday afternoon") — and compresses them into a trait
   vector. Two users with zero shared history still get an informative
   prior if their semantics align. That prior enters the matching model as
   kappa(traits_i, traits_j).

2. ROLE INFERENCE. From event sequences the agent infers social roles the
   linear model has no hypothesis for: initiator vs joiner (creates bounces
   vs accepts them), explorer vs regular, crew size. Initiator/joiner
   complementarity is a real matching signal.

3. EXPLANATIONS THAT ARE ALSO FEATURES. follow_ideas/venue_ideas come with
   <=12-word reasons. The same generation is consumed twice: as a prior
   nudge in the Bayesian model (IDEA_BOOST) and as UI copy.

Costs stay tiny: one call per user per ~3 days, one call per hot venue per
day, all fire-and-forget behind a semaphore.
"""

import asyncio
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.database import create_async_session
from db.models import (
    Bounce,
    BounceInvite,
    CheckInHistory,
    Follow,
    Place,
    User,
    UserAgentProfile,
    VenueAgentProfile,
)

logger = logging.getLogger(__name__)

REFRESH_AFTER = timedelta(days=3)
REFRESH_EVENT_DELTA = 10
DIGEST_WINDOW_DAYS = 120
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

_refresh_semaphore = asyncio.Semaphore(3)
_in_flight: set = set()

PROFILE_SYSTEM = (
    "You are a nightlife and social-scene profiler for a going-out app. "
    "You read a user's real behavior log and produce a JSON dossier. "
    "Be specific and neutral; never mention dating. Respond with ONLY valid JSON."
)

PROFILE_SCHEMA_HINT = """Respond with ONLY this JSON shape:
{
  "persona": "<=70 words, second person, about their going-out character>",
  "traits": {
    "scene_tags": ["<=5 short tags like techno, galleries, rooftops, dive-bars"],
    "nocturnality": 0.0-1.0,
    "spontaneity": 0.0-1.0,
    "initiator": 0.0-1.0,
    "exploration": 0.0-1.0,
    "crew": "solo|duo|small|pack"
  },
  "follow_ideas": [{"user_id": <int from CANDIDATE PEOPLE>, "reason": "<=12 words"}],
  "venue_ideas": [{"place_id": "<id from CANDIDATE VENUES>", "reason": "<=12 words"}]
}
Max 3 follow_ideas and 3 venue_ideas; only pick from the provided candidates; empty lists are fine."""


async def _groq_json(system: str, user: str, max_tokens: int = 500) -> Optional[dict]:
    if not settings.GROQ_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            if resp.status_code != 200:
                logger.warning(f"Groq profile call {resp.status_code}: {resp.text[:200]}")
                return None
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        logger.warning(f"Groq profile call failed: {e}")
        return None


# ---------------- digest ----------------

async def _build_digest(db: AsyncSession, user_id: int) -> tuple[str, int]:
    """Compact behavior log the 8B model can reason over. Returns (text, event_count)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DIGEST_WINDOW_DAYS)

    visits = (await db.execute(
        select(CheckInHistory.place_id, CheckInHistory.venue_name,
               CheckInHistory.checked_in_at, Place.types)
        .outerjoin(Place, CheckInHistory.places_fk_id == Place.id)
        .where(CheckInHistory.user_id == user_id, CheckInHistory.checked_in_at >= cutoff)
        .order_by(CheckInHistory.checked_in_at.desc())
        .limit(120)
    )).all()

    created = (await db.execute(
        select(Bounce.id).where(Bounce.creator_id == user_id, Bounce.created_at >= cutoff)
    )).all()
    invites = (await db.execute(
        select(BounceInvite.status).join(Bounce, BounceInvite.bounce_id == Bounce.id)
        .where(BounceInvite.user_id == user_id, Bounce.created_at >= cutoff)
    )).all()
    n_following = (await db.execute(
        select(Follow.id).where(Follow.follower_id == user_id)
    )).all()
    n_followers = (await db.execute(
        select(Follow.id).where(Follow.following_id == user_id)
    )).all()

    venue_counter: Counter = Counter()
    venue_hours: dict[str, list] = defaultdict(list)
    venue_types: dict[str, set] = defaultdict(set)
    for place_id, name, ts, types_json in visits:
        label = name or place_id
        venue_counter[label] += 1
        if ts:
            venue_hours[label].append(ts.hour)
        try:
            for t in json.loads(types_json) if types_json else []:
                if t not in ("point_of_interest", "establishment"):
                    venue_types[label].add(t)
        except (json.JSONDecodeError, TypeError):
            pass

    lines = []
    for label, count in venue_counter.most_common(15):
        hours = venue_hours.get(label, [])
        hour_note = ""
        if hours:
            avg = sum(hours) / len(hours)
            hour_note = f", usually ~{int(avg):02d}:00"
        types_note = ""
        if venue_types.get(label):
            types_note = f" ({', '.join(sorted(venue_types[label])[:3])})"
        lines.append(f"- {label}{types_note}: {count} visits{hour_note}")

    accepted = sum(1 for (s,) in invites if s == "accepted")
    declined = sum(1 for (s,) in invites if s == "declined")

    digest = (
        f"VENUES (last {DIGEST_WINDOW_DAYS} days):\n" + ("\n".join(lines) or "- none")
        + f"\n\nSOCIAL: created {len(created)} bounces (meetups); "
        f"received {len(invites)} invites, accepted {accepted}, declined {declined}; "
        f"follows {len(n_following)} people, followed by {len(n_followers)}."
    )
    n_events = len(visits) + len(created) + len(invites)
    return digest, n_events


def _candidate_block(people: list[dict], venues: list[dict]) -> str:
    p_lines = [f"- user_id {c['user_id']}: {c['label']}" for c in people[:8]] or ["- none"]
    v_lines = [f"- place_id {c['place_id']}: {c['label']}" for c in venues[:8]] or ["- none"]
    return (
        "\n\nCANDIDATE PEOPLE (crossed paths, not yet followed):\n" + "\n".join(p_lines)
        + "\n\nCANDIDATE VENUES (their crowd overlaps this user's, not yet visited):\n"
        + "\n".join(v_lines)
    )


# ---------------- refresh ----------------

async def refresh_user_profile(
    user_id: int,
    candidate_people: Optional[list[dict]] = None,
    candidate_venues: Optional[list[dict]] = None,
    force: bool = False,
):
    """Fire-and-forget agent refresh. Skips if fresh, in flight, or no key."""
    if not settings.GROQ_API_KEY or user_id in _in_flight:
        return
    _in_flight.add(user_id)
    try:
        async with _refresh_semaphore:
            async with create_async_session() as db:
                existing = (await db.execute(
                    select(UserAgentProfile).where(UserAgentProfile.user_id == user_id)
                )).scalar_one_or_none()

                digest, n_events = await _build_digest(db, user_id)
                if existing and not force:
                    age_ok = existing.updated_at and (
                        datetime.now(timezone.utc) - existing.updated_at < REFRESH_AFTER
                    )
                    growth_ok = n_events - (existing.events_count or 0) < REFRESH_EVENT_DELTA
                    if age_ok and growth_ok:
                        return
                if n_events < 3:
                    return  # nothing to profile yet

                prompt = digest + _candidate_block(candidate_people or [], candidate_venues or []) \
                    + "\n\n" + PROFILE_SCHEMA_HINT
                result = await _groq_json(PROFILE_SYSTEM, prompt)
                if not result:
                    return

                traits = result.get("traits") or {}
                ideas = {
                    "follow_ideas": result.get("follow_ideas") or [],
                    "venue_ideas": result.get("venue_ideas") or [],
                }
                persona = str(result.get("persona") or "")[:600]

                if existing:
                    existing.persona = persona
                    existing.traits = json.dumps(traits)
                    existing.ideas = json.dumps(ideas)
                    existing.events_count = n_events
                else:
                    db.add(UserAgentProfile(
                        user_id=user_id,
                        persona=persona,
                        traits=json.dumps(traits),
                        ideas=json.dumps(ideas),
                        events_count=n_events,
                    ))
                await db.commit()
                logger.info(f"Agent profile refreshed for user {user_id} ({n_events} events)")
    except Exception as e:
        logger.warning(f"Agent profile refresh failed for user {user_id}: {e}")
    finally:
        _in_flight.discard(user_id)


VENUE_SYSTEM = (
    "You summarize the crowd character of a nightlife venue from visitor trait data. "
    "Respond with ONLY valid JSON."
)


async def refresh_venue_profile(place_id: str, visitor_traits: list[dict]):
    """Venue-side agent: one-line vibe from its recent visitors' traits."""
    if not settings.GROQ_API_KEY or not visitor_traits or f"v:{place_id}" in _in_flight:
        return
    _in_flight.add(f"v:{place_id}")
    try:
        async with _refresh_semaphore:
            async with create_async_session() as db:
                existing = (await db.execute(
                    select(VenueAgentProfile).where(VenueAgentProfile.place_id == place_id)
                )).scalar_one_or_none()
                if existing and existing.updated_at and (
                    datetime.now(timezone.utc) - existing.updated_at < timedelta(days=1)
                ):
                    return

                tags: Counter = Counter()
                for t in visitor_traits:
                    for tag in (t.get("scene_tags") or [])[:5]:
                        tags[tag] += 1
                prompt = (
                    f"Venue crowd trait tags (tag: count): "
                    f"{json.dumps(dict(tags.most_common(10)))}\n"
                    'Respond: {"vibe": "<=15 words about who goes here"}'
                )
                result = await _groq_json(VENUE_SYSTEM, prompt, max_tokens=80)
                if not result or not result.get("vibe"):
                    return
                if existing:
                    existing.vibe = str(result["vibe"])[:300]
                    existing.crowd_traits = json.dumps(dict(tags.most_common(10)))
                else:
                    db.add(VenueAgentProfile(
                        place_id=place_id,
                        vibe=str(result["vibe"])[:300],
                        crowd_traits=json.dumps(dict(tags.most_common(10))),
                    ))
                await db.commit()
    except Exception as e:
        logger.warning(f"Venue agent refresh failed for {place_id}: {e}")
    finally:
        _in_flight.discard(f"v:{place_id}")


async def get_persona(db: AsyncSession, user_id: int) -> Optional[dict]:
    row = (await db.execute(
        select(UserAgentProfile).where(UserAgentProfile.user_id == user_id)
    )).scalar_one_or_none()
    if not row:
        return None
    try:
        traits = json.loads(row.traits) if row.traits else {}
    except (json.JSONDecodeError, TypeError):
        traits = {}
    try:
        ideas = json.loads(row.ideas) if row.ideas else {}
    except (json.JSONDecodeError, TypeError):
        ideas = {}
    return {
        "persona": row.persona,
        "traits": traits,
        "ideas": ideas,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
