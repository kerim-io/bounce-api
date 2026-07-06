"""Bayesian social matching engine — "who at this venue would you click with,
and where should you head right now".

The model, precisely:

For each ordered pair (i -> j) there is a latent directed affinity

    A_ij ~ N(mu0_ij, sigma0_ij^2)                                  (prior)

  mu0_ij = b + w_t * taste(i,j) + w_g * graph(i,j)
             + w_k * kappa(traits_i, traits_j) + w_m * magnetism_z(j)
             + idea_boost(i,j)

  - taste:  cosine of the ALS user factors from services/recommendations
            (people who like the same venues)
  - graph:  normalized dot of NetMF social-graph embeddings (network effect)
  - kappa:  deterministic compatibility kernel over the LLM agent's trait
            vectors (semantic prior — carries signal where the collaborative
            data is coldest)
  - magnetism_z(j): j's follow-through rate after co-presence, a Beta
            posterior Beta(1+s, 9+f); its mean is standardized into a z-score
            and its VARIANCE is propagated into the pair's prior variance
            (hierarchical uncertainty: an unknown newcomer widens the prior
            rather than shifting it)
  - idea_boost: +0.3 when i's profile agent explicitly proposed j
  - b: intercept calibrated so the average uninformed pair's match
       probability equals the empirical base rate rho of
       P(follow | co-presence):  b = tau + sigma_bar * PHI^-1(rho) - fbar

Evidence: each behavioral event e between the pair observes A_ij through a
Gaussian likelihood y_e ~ N(A_ij, sigma_e^2), discounted by recency as a
power likelihood with weight d_e = exp(-age_e / 90d). Conjugacy gives the
closed-form posterior

    lambda_post = 1/sigma0^2 + SUM_e d_e / sigma_e^2
    mu_post     = (mu0/sigma0^2 + SUM_e d_e * y_e / sigma_e^2) / lambda_post

and the number surfaced to users is the probit tail

    p(i->j) = P(A_ij > tau) = 1 - PHI((tau - mu_post) * sqrt(lambda_post))

so a pair with little evidence keeps a wide posterior and shrinks toward the
calibrated base rate instead of screaming 97% off one follow. The mutual
match probability is p(i->j) * p(j->i) under the usual independence
approximation.

Where the evidence comes from (the part that makes it a *social* model):
follows are classified by whether both users were checked into the same
venue when the follow happened (met-in-person signal) vs anywhere else;
post-connection co-check-ins, bounce invites sent/accepted/declined,
co-bounce attendance, and close-friend upgrades all observe the latent;
repeated co-presence with NO action is weak negative evidence (exposure
without a click). Unfollows would be strong negative evidence but follows
are hard-deleted today — noted for a future event log.
"""

import asyncio
import json
import logging
import math
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from statistics import NormalDist
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Bounce,
    BounceAttendee,
    BounceInvite,
    CheckIn,
    CheckInHistory,
    Follow,
    Place,
    UserAgentProfile,
)

logger = logging.getLogger(__name__)

# ---------------- constants ----------------

# Evidence table: event type -> (observed value y_e, observation noise sigma_e)
EVIDENCE = {
    "follow_at_venue":        (2.2, 0.6),   # followed while co-present — the core signal
    "follow_elsewhere":       (1.2, 0.9),
    "follow_back_fast":       (1.8, 0.7),   # reciprocated within 48h
    "close_friend":           (2.8, 0.5),
    "bounce_invite_sent":     (1.6, 0.8),
    "bounce_invite_accepted": (1.9, 0.7),
    "bounce_invite_declined": (-1.4, 1.0),
    "co_checkin_after":       (1.5, 0.8),   # kept hanging out after connecting
    "co_bounce":              (1.8, 0.7),
    "exposure_no_action":     (-0.4, 1.5),  # co-present, never followed
}

DECAY_DAYS = 90.0
PRIOR_VAR = 1.0
TAU = 1.0                      # affinity threshold defining a "match"
MAG_VAR_SCALE = 4.0            # how strongly magnetism uncertainty widens the prior

W_TASTE, W_GRAPH, W_KAPPA, W_MAG = 0.8, 0.6, 0.5, 0.4
IDEA_BOOST = 0.3

HISTORY_WINDOW_DAYS = 180
MAX_HISTORY_ROWS = 30000
OVERLAP_MIN_S = 15 * 60        # >=15 min together counts as co-presence
FOLLOW_SLACK_S = 45 * 60       # follow within +/-45 min of shared presence
DEFAULT_STAY_S = 4 * 3600      # open-ended check-ins assumed 4h
EXPOSURE_CAP = 5
FOLLOW_BACK_FAST_S = 48 * 3600
MODEL_TTL_SECONDS = 600
MAX_ACTIVE_SWEEP = 50          # cap concurrent intervals per venue sweep

_STD_NORMAL = NormalDist()


def _phi(x: float) -> float:
    return _STD_NORMAL.cdf(x)


def _phi_inv(p: float) -> float:
    return _STD_NORMAL.inv_cdf(min(max(p, 1e-6), 1 - 1e-6))


def _decay(age_seconds: float) -> float:
    return math.exp(-max(age_seconds, 0.0) / (DECAY_DAYS * 86400))


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------- trait compatibility kernel ----------------

def trait_compat(a: Optional[dict], b: Optional[dict]) -> float:
    """Deterministic kernel over LLM-emitted trait vectors, in [-1, 1].
    Shared scene tags and aligned rhythms attract; initiator/joiner
    complementarity is a mild bonus (organizers pair with joiners)."""
    if not a or not b:
        return 0.0
    tags_a = set(a.get("scene_tags") or [])
    tags_b = set(b.get("scene_tags") or [])
    union = tags_a | tags_b
    jac = (len(tags_a & tags_b) / len(union)) if union else 0.0

    def _f(d, key):
        try:
            return min(max(float(d.get(key, 0.5)), 0.0), 1.0)
        except (TypeError, ValueError):
            return 0.5

    noct_align = 1.0 - abs(_f(a, "nocturnality") - _f(b, "nocturnality"))
    expl_align = 1.0 - abs(_f(a, "exploration") - _f(b, "exploration"))
    init_comp = abs(_f(a, "initiator") - _f(b, "initiator"))

    score = (
        0.45 * (2 * jac - 0.5)
        + 0.30 * (2 * noct_align - 1)
        + 0.15 * (2 * expl_align - 1)
        + 0.10 * (2 * init_comp - 1)
    )
    return min(max(score, -1.0), 1.0)


# ---------------- model ----------------

class MatchingModel:
    def __init__(self):
        self.built_at: float = 0
        # (i, j) -> list[(event_type, epoch_ts)]
        self.evidence: dict[tuple, list] = defaultdict(list)
        self.following: dict[int, set] = defaultdict(set)
        self.magnetism_z: dict[int, float] = {}
        self.magnetism_var: dict[int, float] = {}
        self.traits: dict[int, dict] = {}
        self.idea_pairs: dict[tuple, str] = {}      # (i, j) -> reason
        self.venue_ideas: dict[tuple, str] = {}     # (user, place_id) -> reason
        # recsys embeddings (optional)
        self.rec_user_index: dict[int, int] = {}
        self.rec_X = None
        self.rec_G = None
        self.b: float = 0.0                         # calibrated intercept
        # digest inputs for the profile agent
        self.copresence_partners: dict[int, dict[int, int]] = defaultdict(dict)

    @property
    def is_fresh(self) -> bool:
        return time.time() - self.built_at < MODEL_TTL_SECONDS


_model = MatchingModel()
_model_lock = asyncio.Lock()


async def _load_raw(db: AsyncSession) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_WINDOW_DAYS)

    checkins = (await db.execute(
        select(CheckInHistory.user_id, CheckInHistory.place_id,
               CheckInHistory.checked_in_at, CheckInHistory.checked_out_at)
        .where(CheckInHistory.checked_in_at >= cutoff)
        .order_by(CheckInHistory.checked_in_at.desc())
        .limit(MAX_HISTORY_ROWS)
    )).all()

    follows = (await db.execute(
        select(Follow.follower_id, Follow.following_id, Follow.created_at,
               Follow.close_friend_status)
    )).all()

    invites = (await db.execute(
        select(BounceInvite.user_id, BounceInvite.status,
               Bounce.creator_id, Bounce.created_at, Bounce.id)
        .join(Bounce, BounceInvite.bounce_id == Bounce.id)
        .where(Bounce.created_at >= cutoff)
    )).all()

    attendees = (await db.execute(
        select(BounceAttendee.bounce_id, BounceAttendee.user_id, BounceAttendee.joined_at)
        .join(Bounce, BounceAttendee.bounce_id == Bounce.id)
        .where(Bounce.created_at >= cutoff)
    )).all()

    profiles = (await db.execute(
        select(UserAgentProfile.user_id, UserAgentProfile.traits, UserAgentProfile.ideas)
    )).all()

    return {
        "checkins": checkins,
        "follows": follows,
        "invites": invites,
        "attendees": attendees,
        "profiles": profiles,
        "now": datetime.now(timezone.utc),
    }


def _fit(raw: dict, recsys=None) -> MatchingModel:
    """CPU-bound fit. `recsys` is the RecommendationModel (taste + graph
    embeddings feed the prior); tolerated as None."""
    m = MatchingModel()
    now: datetime = raw["now"]
    now_ts = now.timestamp()

    def ts(dt) -> float:
        if dt is None:
            return now_ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    # ---- interval index per user + per venue ----
    intervals_by_user: dict[int, list] = defaultdict(list)   # (place, s, e)
    intervals_by_place: dict[str, list] = defaultdict(list)  # (user, s, e)
    for user_id, place_id, cin, cout in raw["checkins"]:
        if not place_id:
            continue
        s = ts(cin)
        e = ts(cout) if cout is not None else min(s + DEFAULT_STAY_S, now_ts)
        if e <= s:
            e = s + 15 * 60
        intervals_by_user[user_id].append((place_id, s, e))
        intervals_by_place[place_id].append((user_id, s, e))

    # ---- follows: classify at-venue vs elsewhere; reciprocity; close friends ----
    follow_ts: dict[tuple, float] = {}
    close_pairs: set = set()
    for f, g, created, cf_status in raw["follows"]:
        m.following[f].add(g)
        t = ts(created)
        follow_ts[(f, g)] = t
        if cf_status == "accepted":
            close_pairs.add((min(f, g), max(f, g)))

    def _at_same_venue(u: int, v: int, t: float) -> bool:
        places_u = {
            p for (p, s, e) in intervals_by_user.get(u, [])
            if s - FOLLOW_SLACK_S <= t <= e + FOLLOW_SLACK_S
        }
        if not places_u:
            return False
        for (p, s, e) in intervals_by_user.get(v, []):
            if p in places_u and s - FOLLOW_SLACK_S <= t <= e + FOLLOW_SLACK_S:
                return True
        return False

    for (f, g), t in follow_ts.items():
        etype = "follow_at_venue" if _at_same_venue(f, g, t) else "follow_elsewhere"
        m.evidence[(f, g)].append((etype, t))
        # fast reciprocation is mutual evidence
        t_back = follow_ts.get((g, f))
        if t_back is not None and 0 < t_back - t <= FOLLOW_BACK_FAST_S:
            m.evidence[(g, f)].append(("follow_back_fast", t_back))
            m.evidence[(f, g)].append(("follow_back_fast", t_back))

    for (a, b) in close_pairs:
        t = max(follow_ts.get((a, b), now_ts), follow_ts.get((b, a), now_ts))
        m.evidence[(a, b)].append(("close_friend", t))
        m.evidence[(b, a)].append(("close_friend", t))

    def first_follow_ts(u: int, v: int) -> Optional[float]:
        t1 = follow_ts.get((u, v))
        t2 = follow_ts.get((v, u))
        if t1 is None and t2 is None:
            return None
        return min(t for t in (t1, t2) if t is not None)

    # ---- co-presence sweep per venue ----
    copresence: dict[tuple, list] = defaultdict(list)  # unordered pair -> [ts]
    for place_id, ivs in intervals_by_place.items():
        ivs.sort(key=lambda x: x[1])
        active: list = []
        for (u, s, e) in ivs:
            active = [(v, vs, ve) for (v, vs, ve) in active if ve > s][-MAX_ACTIVE_SWEEP:]
            for (v, vs, ve) in active:
                if v == u:
                    continue
                overlap = min(e, ve) - max(s, vs)
                if overlap >= OVERLAP_MIN_S:
                    key = (min(u, v), max(u, v))
                    copresence[key].append(max(s, vs))
            active.append((u, s, e))

    # exposure & post-connection co-check-ins + magnetism counting
    exposures_of: dict[int, int] = defaultdict(int)     # j -> co-presence exposures
    followed_after: dict[int, int] = defaultdict(int)   # j -> got followed after co-presence
    for (u, v), events in copresence.items():
        events.sort()
        m.copresence_partners[u][v] = len(events)
        m.copresence_partners[v][u] = len(events)
        fft = first_follow_ts(u, v)
        if fft is None:
            # never connected: repeated exposure without action is negative
            # evidence — the first meeting is a free pass
            for t in events[1:][-EXPOSURE_CAP:]:
                m.evidence[(u, v)].append(("exposure_no_action", t))
                m.evidence[(v, u)].append(("exposure_no_action", t))
        else:
            for t in events:
                if t > fft:
                    m.evidence[(u, v)].append(("co_checkin_after", t))
                    m.evidence[(v, u)].append(("co_checkin_after", t))
        # magnetism tallies (both roles)
        for (a, b) in ((u, v), (v, u)):
            exposures_of[b] += 1
            t_follow = follow_ts.get((a, b))
            if t_follow is not None and events and t_follow >= events[0] - FOLLOW_SLACK_S:
                followed_after[b] += 1

    # ---- bounce invites & co-attendance ----
    for user_id, status, creator_id, created, _bid in raw["invites"]:
        if user_id == creator_id:
            continue
        t = ts(created)
        m.evidence[(creator_id, user_id)].append(("bounce_invite_sent", t))
        if status == "accepted":
            m.evidence[(user_id, creator_id)].append(("bounce_invite_accepted", t))
        elif status == "declined":
            m.evidence[(user_id, creator_id)].append(("bounce_invite_declined", t))

    by_bounce: dict[int, list] = defaultdict(list)
    for bounce_id, user_id, joined in raw["attendees"]:
        by_bounce[bounce_id].append((user_id, ts(joined)))
    for bounce_id, members in by_bounce.items():
        if len(members) > 30:
            members = members[:30]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                (u, tu), (v, tv) = members[i], members[j]
                if u == v:
                    continue
                t = max(tu, tv)
                m.evidence[(u, v)].append(("co_bounce", t))
                m.evidence[(v, u)].append(("co_bounce", t))

    # ---- magnetism: Beta(1+s, 9+f) posterior per user ----
    means = {}
    for j, n in exposures_of.items():
        s = followed_after.get(j, 0)
        alpha, beta = 1.0 + s, 9.0 + max(n - s, 0)
        means[j] = alpha / (alpha + beta)
        m.magnetism_var[j] = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
    if means:
        vals = list(means.values())
        mu_pop = sum(vals) / len(vals)
        sd_pop = math.sqrt(sum((v - mu_pop) ** 2 for v in vals) / len(vals)) or 1e-3
        for j, v in means.items():
            m.magnetism_z[j] = min(max((v - mu_pop) / sd_pop, -2.0), 2.0)

    # ---- agent traits + ideas ----
    for user_id, traits_json, ideas_json in raw["profiles"]:
        try:
            m.traits[user_id] = json.loads(traits_json) if traits_json else {}
        except (json.JSONDecodeError, TypeError):
            m.traits[user_id] = {}
        try:
            ideas = json.loads(ideas_json) if ideas_json else {}
        except (json.JSONDecodeError, TypeError):
            ideas = {}
        for idea in ideas.get("follow_ideas", []) or []:
            try:
                m.idea_pairs[(user_id, int(idea.get("user_id")))] = str(idea.get("reason") or "")
            except (TypeError, ValueError):
                continue
        for idea in ideas.get("venue_ideas", []) or []:
            pid = idea.get("place_id")
            if pid:
                m.venue_ideas[(user_id, str(pid))] = str(idea.get("reason") or "")

    # ---- recsys embeddings for the prior ----
    if recsys is not None:
        m.rec_user_index = dict(recsys.user_index)
        m.rec_X = recsys.X
        m.rec_G = recsys.G

    # ---- calibrate intercept b to the empirical base rate ----
    # rho = P(followed | co-presence exposure), floored to keep PHI^-1 sane
    total_exp = sum(exposures_of.values())
    total_fol = sum(followed_after.values())
    rho = (total_fol / total_exp) if total_exp >= 20 else 0.10
    rho = min(max(rho, 0.01), 0.5)
    sigma_bar = math.sqrt(PRIOR_VAR)
    # uninformed pair: features ~ 0, so mu0 = b; want P(A > tau) = rho
    m.b = TAU + sigma_bar * _phi_inv(rho)

    m.built_at = time.time()
    logger.info(
        f"Matching model: {len(m.evidence)} evidenced pairs, "
        f"{len(copresence)} co-present pairs, base_rate={rho:.3f}, b={m.b:.3f}"
    )
    return m


async def get_matching_model(db: AsyncSession) -> MatchingModel:
    global _model
    if _model.is_fresh:
        return _model
    async with _model_lock:
        if _model.is_fresh:
            return _model
        raw = await _load_raw(db)
        recsys = None
        try:
            from services.recommendations import get_model as get_recsys_model
            recsys = await get_recsys_model(db)
        except Exception as e:
            logger.warning(f"Matching: recsys model unavailable for priors: {e}")
        _model = await asyncio.to_thread(_fit, raw, recsys)
        return _model


# ---------------- posterior ----------------

def _embedding_sims(m: MatchingModel, i: int, j: int) -> tuple[float, float]:
    """(taste_cosine, graph_dot_normalized), both in [-1, 1]."""
    taste = graph = 0.0
    ui, uj = m.rec_user_index.get(i), m.rec_user_index.get(j)
    if ui is not None and uj is not None:
        X, G = m.rec_X, m.rec_G
        if X is not None and ui < X.shape[0] and uj < X.shape[0]:
            xi, xj = X[ui], X[uj]
            ni, nj = (xi @ xi) ** 0.5, (xj @ xj) ** 0.5
            if ni > 1e-9 and nj > 1e-9:
                taste = float(xi @ xj / (ni * nj))
        if G is not None and ui < G.shape[0] and uj < G.shape[0]:
            gi, gj = G[ui], G[uj]
            ni, nj = (gi @ gi) ** 0.5, (gj @ gj) ** 0.5
            if ni > 1e-9 and nj > 1e-9:
                graph = float(gi @ gj / (ni * nj))
    return taste, graph


def pair_posterior(m: MatchingModel, i: int, j: int, now_ts: Optional[float] = None) -> dict:
    """Full posterior for A_(i->j): mean, sd, tail probability, contributions."""
    now_ts = now_ts or time.time()

    taste, graph = _embedding_sims(m, i, j)
    kappa = trait_compat(m.traits.get(i), m.traits.get(j))
    mag_z = m.magnetism_z.get(j, 0.0)
    idea = IDEA_BOOST if (i, j) in m.idea_pairs else 0.0

    mu0 = m.b + W_TASTE * taste + W_GRAPH * graph + W_KAPPA * kappa + W_MAG * mag_z + idea
    var0 = PRIOR_VAR + MAG_VAR_SCALE * m.magnetism_var.get(j, 0.0)

    lam = 1.0 / var0
    num = mu0 / var0
    contribs: dict[str, float] = {}
    for (etype, t) in m.evidence.get((i, j), []):
        y, sigma = EVIDENCE[etype]
        d = _decay(now_ts - t)
        lam += d / (sigma * sigma)
        num += d * y / (sigma * sigma)
        contribs[etype] = contribs.get(etype, 0.0) + d * y / (sigma * sigma)

    mu_post = num / lam
    sd_post = math.sqrt(1.0 / lam)
    p = 1.0 - _phi((TAU - mu_post) / sd_post)

    return {
        "mu": mu_post,
        "sd": sd_post,
        "p": p,
        "prior_mu": mu0,
        "taste": taste,
        "graph": graph,
        "kappa": kappa,
        "magnetism": mag_z,
        "idea": idea != 0.0,
        "contribs": contribs,
    }


def match_pair(m: MatchingModel, i: int, j: int, now_ts: Optional[float] = None) -> dict:
    """Directed posteriors both ways + mutual match probability + reasons."""
    a = pair_posterior(m, i, j, now_ts)
    b = pair_posterior(m, j, i, now_ts)
    mutual = a["p"] * b["p"]
    return {
        "p_i_to_j": round(a["p"], 4),
        "p_j_to_i": round(b["p"], 4),
        "match_probability": round(mutual, 4),
        "reasons": _reasons(m, i, j, a, b),
        "_detail": {"i_to_j": a, "j_to_i": b},
    }


def _reasons(m: MatchingModel, i: int, j: int, a: dict, b: dict) -> list[str]:
    reasons: list[str] = []
    idea_reason = m.idea_pairs.get((i, j))
    if idea_reason:
        reasons.append(idea_reason)
    contribs = a["contribs"]
    if contribs.get("co_checkin_after", 0) > 0 or contribs.get("co_bounce", 0) > 0:
        reasons.append("You keep ending up at the same places")
    if contribs.get("follow_back_fast", 0) > 0:
        reasons.append("Quick mutual follow")
    if b["contribs"].get("follow_at_venue", 0) > 0:
        reasons.append("They followed you when you crossed paths")
    if a["kappa"] > 0.3:
        tags_i = set((m.traits.get(i) or {}).get("scene_tags") or [])
        tags_j = set((m.traits.get(j) or {}).get("scene_tags") or [])
        shared = sorted(tags_i & tags_j)[:2]
        if shared:
            reasons.append("Same scene: " + ", ".join(shared))
        else:
            reasons.append("Similar rhythm — same nights, same energy")
    if a["taste"] > 0.4 and not reasons:
        reasons.append("You like the same venues")
    n = m.copresence_partners.get(i, {}).get(j, 0)
    if n >= 2 and not any("same places" in r for r in reasons):
        reasons.append(f"Crossed paths {n} times")
    if not reasons:
        reasons.append("New face on your scene")
    return reasons[:2]


# ---------------- serving ----------------

def rank_people(m: MatchingModel, viewer: int, candidates: list[int]) -> list[dict]:
    """Rank candidate users for the viewer. Excludes people the viewer
    already follows (nothing to prompt) and self."""
    now_ts = time.time()
    out = []
    already = m.following.get(viewer, set())
    for j in candidates:
        if j == viewer or j in already:
            continue
        pair = match_pair(m, viewer, j, now_ts)
        detail = pair.pop("_detail")
        pair["user_id"] = j
        pair["uncertain"] = detail["i_to_j"]["sd"] > 0.85  # mostly-prior pairs
        out.append(pair)
    out.sort(key=lambda r: r["match_probability"], reverse=True)
    return out


def rank_venues_now(
    m: MatchingModel,
    viewer: int,
    occupants_by_place: dict[str, list[int]],
    place_meta: dict[str, dict],
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    exclude_place: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Score venues by the expected number of promising encounters there
    RIGHT NOW: E_v = sum over current occupants of mutual match probability,
    distance-decayed. Agent venue ideas add a small bonus.

    Unlike rank_people (a follow prompt, so existing follows are excluded),
    this INCLUDES people the viewer already connected with — a high-affinity
    existing connection being somewhere is exactly the pull that should move
    someone across town."""
    now_ts = time.time()
    results = []
    for place_id, users in occupants_by_place.items():
        if place_id == exclude_place:
            continue
        meta = place_meta.get(place_id, {})
        scored = []
        for j in users:
            if j == viewer:
                continue
            pair = match_pair(m, viewer, j, now_ts)
            scored.append((pair["match_probability"], j, pair))
        if not scored:
            continue
        scored.sort(reverse=True)
        expected = sum(s for s, _, _ in scored)
        score = expected
        idea_reason = m.venue_ideas.get((viewer, place_id))
        if idea_reason:
            score *= 1.25
        distance_m = None
        if lat is not None and lng is not None and meta.get("lat") is not None:
            distance_m = _haversine_m(lat, lng, meta["lat"], meta["lng"])
            score *= math.exp(-distance_m / 3500.0)
        results.append({
            "place_id": place_id,
            "name": meta.get("name"),
            "latitude": meta.get("lat"),
            "longitude": meta.get("lng"),
            "distance_m": round(distance_m) if distance_m is not None else None,
            "people_here": len(users),
            "expected_matches": round(expected, 3),
            "score": round(score, 4),
            "reason": idea_reason or (
                f"{len(scored)} people you might click with are here now"
                if len(scored) > 1 else "Someone you might click with is here now"
            ),
            "top_people": [
                {"user_id": j, "match_probability": round(s, 4)}
                for s, j, _ in scored[:3]
            ],
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


async def get_active_occupants(db: AsyncSession, expiry_hours: int = 24) -> dict[str, list[int]]:
    """Who is checked in where, right now."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=expiry_hours)
    rows = (await db.execute(
        select(CheckIn.place_id, CheckIn.user_id)
        .where(CheckIn.is_active == True, CheckIn.last_seen_at >= cutoff)  # noqa: E712
    )).all()
    out: dict[str, list[int]] = defaultdict(list)
    for place_id, user_id in rows:
        if place_id:
            out[place_id].append(user_id)
    return dict(out)


async def get_place_meta(db: AsyncSession, place_ids: list[str]) -> dict[str, dict]:
    if not place_ids:
        return {}
    rows = (await db.execute(
        select(Place.place_id, Place.name, Place.latitude, Place.longitude)
        .where(Place.place_id.in_(place_ids))
    )).all()
    return {pid: {"name": name, "lat": lat, "lng": lng} for pid, name, lat, lng in rows}
