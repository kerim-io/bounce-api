"""Place recommendation engine.

Pipeline (rebuilt in-memory every ~10 min, numpy only):

1. INTERACTION MATRIX — user × venue implicit feedback. Strong signal:
   check-ins (recency-decayed) and attended bounces. Weak signals, weighted
   lower: venue feed posts, and logged place/feed views (user_place_events).

2. COLLABORATIVE FILTERING — implicit-feedback ALS matrix factorization
   (Hu–Koren–Volinsky) over that matrix. User/venue latent factors capture
   "people like you go here" without hand-built co-visitation heuristics.

3. GRAPH EMBEDDINGS — the social graph (follows weighted by tie strength:
   mutual > one-way, close friends strongest; plus co-attendance edges) is
   embedded NetMF-style: skip-gram node2vec is implicit factorization of the
   random-walk PMI matrix (Qiu et al., WSDM'18), so we factorize that matrix
   directly with SVD. Venues get embeddings by bipartite projection of their
   visitors — the network effect becomes a dense feature, not a one-hop rule.

4. LEARNED RANKER — a pointwise logistic ranker fuses MF score, graph
   affinity, category match, popularity, friend strength, novelty and
   distance into one relevance score. Trained on a time-split: each user's
   most recent check-ins are held-out positives vs. sampled negatives.
   Falls back to calibrated default weights when data is too thin. The
   feature interface is exactly what a LightGBM/two-tower upgrade would take.

5. SERVING — candidates = top-K by MF dot product (brute-force argpartition;
   the FAISS/ANN slot once the venue count justifies it) ∪ network venues ∪
   popular, then ranked. Every suggestion carries human-readable reasons.
"""

import asyncio
import json
import logging
import math
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import create_async_session
from db.models import (
    Bounce,
    BounceAttendee,
    CheckInHistory,
    Follow,
    Place,
    UserPlaceEvent,
    VenueFeedMessage,
)

logger = logging.getLogger(__name__)

# --- Signal weights into the interaction matrix ---
W_CHECKIN = 1.0
W_BOUNCE_ATTENDED = 1.5
W_FEED_POST = 0.5
W_FEED_VIEW = 0.25
W_PLACE_VIEW = 0.2      # looked at details after search — weak positive

RECENCY_HALF_LIFE_DAYS = 30.0
HISTORY_WINDOW_DAYS = 120
MAX_HISTORY_ROWS = 20000
MODEL_TTL_SECONDS = 600

# ALS hyperparameters
MF_FACTORS = 32
MF_ALPHA = 40.0
MF_REG = 0.1
MF_ITERS = 12

# Graph embedding
GRAPH_DIM = 16
TIE_ONE_WAY = 0.35
TIE_MUTUAL = 1.0
TIE_CLOSE_FRIEND = 1.5
CO_ATTEND_WEIGHT = 0.5

# Personalized PageRank over the joint social+check-in graph: a random walk
# from the user through friends -> their venues -> those venues' visitors ->
# THEIR friends -> ... with restart. Every hop contributes with geometrically
# decaying influence — the explicit "and so on" network effect.
PPR_DAMPING = 0.85
PPR_ITERS = 15
PPR_MAX_NODES = 4000        # dense power iteration guard
ALL_TIME_FLOOR = 0.08       # "ever" check-ins never fully vanish

# Serving
CANDIDATE_POOL = 200
PPR_CANDIDATES = 50
DISTANCE_SCALE_M = 3500.0
EXCLUDED_TYPES = {"lodging", "hospital", "doctor", "pharmacy", "gas_station",
                  "car_repair", "atm", "bank", "dentist", "physiotherapist"}

# Ranker features: [mf, graph, category, popularity, social, novelty, distance, network_flow]
N_FEATURES = 8
DEFAULT_RANKER_W = np.array([0.9, 0.8, 0.5, 0.4, 0.9, 0.6, 1.0, 1.1], dtype=np.float64)
DEFAULT_RANKER_B = -1.0
MIN_TRAIN_POSITIVES = 50


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------- numerics


def _als_implicit(R: np.ndarray, factors: int, alpha: float, reg: float,
                  iters: int, seed: int = 7):
    """Weighted implicit-feedback ALS (Hu–Koren–Volinsky)."""
    rng = np.random.default_rng(seed)
    n_users, n_items = R.shape
    f = min(factors, max(2, min(n_users, n_items) - 1))
    X = rng.normal(0, 0.01, (n_users, f))
    Y = rng.normal(0, 0.01, (n_items, f))

    def step(R_, Y_):
        YtY = Y_.T @ Y_
        out = np.zeros((R_.shape[0], f))
        eye = np.eye(f)
        for u in range(R_.shape[0]):
            idx = np.nonzero(R_[u])[0]
            if idx.size == 0:
                continue
            cu = alpha * R_[u, idx]                     # confidence - 1
            Yu = Y_[idx]
            A = YtY + Yu.T @ (cu[:, None] * Yu) + reg * eye
            b = Yu.T @ (1.0 + cu)                       # preference p=1
            out[u] = np.linalg.solve(A, b)
        return out

    for _ in range(iters):
        X = step(R, Y)
        Y = step(R.T, X)
    return X, Y


def _netmf_embeddings(adj: np.ndarray, dim: int):
    """NetMF-lite: factorize the window-2 random-walk PMI matrix with SVD.
    Equivalent objective to skip-gram node2vec (Qiu et al. 2018), no walks needed."""
    n = adj.shape[0]
    if n == 0:
        return np.zeros((0, dim))
    deg = adj.sum(axis=1)
    deg_safe = np.maximum(deg, 1e-9)
    P = adj / deg_safe[:, None]
    M = (P + P @ P) / 2.0
    vol = max(adj.sum(), 1e-9)
    pmi = np.log1p(M * (vol / np.maximum(deg_safe[None, :], 1e-9)))
    try:
        U, S, _ = np.linalg.svd(pmi, full_matrices=False)
    except np.linalg.LinAlgError:
        return np.zeros((n, dim))
    k = min(dim, S.shape[0])
    emb = U[:, :k] * np.sqrt(np.maximum(S[:k], 0))
    if k < dim:
        emb = np.pad(emb, ((0, 0), (0, dim - k)))
    return emb


def _fit_logistic(F: np.ndarray, y: np.ndarray, epochs=300, lr=0.1, l2=1e-3):
    """Pointwise logistic LTR on standardized features."""
    w = np.zeros(F.shape[1])
    b = 0.0
    n = F.shape[0]
    for _ in range(epochs):
        z = F @ w + b
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        g = p - y
        w -= lr * (F.T @ g / n + l2 * w)
        b -= lr * g.mean()
    return w, b


# ---------------------------------------------------------------- model


class RecommendationModel:
    def __init__(self):
        self.built_at: float = 0
        self.user_index: dict[int, int] = {}
        self.venue_index: dict[str, int] = {}
        self.venue_ids: list[str] = []
        self.X = np.zeros((0, MF_FACTORS))      # user MF factors
        self.Y = np.zeros((0, MF_FACTORS))      # venue MF factors
        self.G = np.zeros((0, GRAPH_DIM))       # user graph embeddings
        self.GV = np.zeros((0, GRAPH_DIM))      # venue graph embeddings (projection)
        self.R_sparse: dict[int, dict[int, float]] = {}   # u_idx -> {v_idx: w}
        self.ties: dict[int, dict[int, float]] = {}       # user_id -> {friend_id: strength}
        self.venue_visitors: dict[int, dict[int, float]] = {}  # v_idx -> {user_id: w}
        self.venue_meta: list[dict] = []
        self.user_cat: dict[int, dict[str, float]] = {}   # u_idx -> type weights
        self.popularity = np.zeros(0)
        self.centroids: dict[int, tuple] = {}             # user_id -> (lat, lng)
        self.ranker_w = DEFAULT_RANKER_W.copy()
        self.ranker_b = DEFAULT_RANKER_B
        self.feat_mean = np.zeros(N_FEATURES)
        self.feat_std = np.ones(N_FEATURES)
        self.ranker_learned = False
        self.metrics: Optional[dict] = None
        self.n_interactions = 0
        # Joint user+venue random-walk matrix (row-stochastic) for PPR
        self.W_joint: Optional[np.ndarray] = None
        self._ppr_cache: dict[int, np.ndarray] = {}

    @property
    def is_fresh(self) -> bool:
        return time.time() - self.built_at < MODEL_TTL_SECONDS


_model = RecommendationModel()
_model_lock = asyncio.Lock()


async def _load_raw(db: AsyncSession) -> dict:
    """Pull everything the fit needs out of Postgres."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_WINDOW_DAYS)

    checkins = (await db.execute(
        select(CheckInHistory.user_id, CheckInHistory.place_id,
               CheckInHistory.checked_in_at, CheckInHistory.latitude, CheckInHistory.longitude)
        .where(CheckInHistory.checked_in_at >= cutoff)
        .order_by(CheckInHistory.checked_in_at.desc())
        .limit(MAX_HISTORY_ROWS)
    )).all()

    # "Ever": pre-window check-ins, aggregated — floor weight, never vanishes
    from sqlalchemy import func as sa_func
    old_checkins = (await db.execute(
        select(CheckInHistory.user_id, CheckInHistory.place_id,
               sa_func.count(CheckInHistory.id))
        .where(CheckInHistory.checked_in_at < cutoff)
        .group_by(CheckInHistory.user_id, CheckInHistory.place_id)
        .limit(MAX_HISTORY_ROWS)
    )).all()

    bounces = (await db.execute(
        select(BounceAttendee.user_id, Bounce.place_id, Bounce.bounce_time)
        .join(Bounce, BounceAttendee.bounce_id == Bounce.id)
        .where(Bounce.bounce_time >= cutoff, Bounce.place_id.isnot(None))
    )).all()

    feed_posts = (await db.execute(
        select(VenueFeedMessage.user_id, VenueFeedMessage.place_id, VenueFeedMessage.created_at)
        .where(VenueFeedMessage.created_at >= cutoff)
    )).all()

    events = (await db.execute(
        select(UserPlaceEvent.user_id, UserPlaceEvent.place_id,
               UserPlaceEvent.event_type, UserPlaceEvent.created_at)
        .where(UserPlaceEvent.created_at >= cutoff)
        .limit(MAX_HISTORY_ROWS)
    )).all()

    follows = (await db.execute(
        select(Follow.follower_id, Follow.following_id, Follow.close_friend_status)
    )).all()

    places = (await db.execute(
        select(Place.id, Place.place_id, Place.name, Place.address,
               Place.latitude, Place.longitude, Place.types, Place.bounce_count)
    )).all()

    return {
        "checkins": checkins, "old_checkins": old_checkins, "bounces": bounces,
        "feed_posts": feed_posts, "events": events, "follows": follows,
        "places": places, "now": datetime.now(timezone.utc),
    }


def _build_rows(raw: dict):
    """Interaction rows (user_id, place_id, weight, ts) + coord samples."""
    now = raw["now"]

    def decay(ts) -> float:
        if ts is None:
            return 0.5 ** (HISTORY_WINDOW_DAYS / RECENCY_HALF_LIFE_DAYS)
        age = max(0.0, (now - ts).total_seconds() / 86400)
        return 0.5 ** (age / RECENCY_HALF_LIFE_DAYS)

    rows = []
    coords: dict[int, list] = defaultdict(list)
    for uid, pid, ts, lat, lng in raw["checkins"]:
        if pid:
            rows.append((uid, pid, W_CHECKIN * decay(ts), ts))
            coords[uid].append((lat, lng, decay(ts)))
    for uid, pid, ts in raw["bounces"]:
        rows.append((uid, pid, W_BOUNCE_ATTENDED * decay(ts), ts))
    for uid, pid, ts in raw["feed_posts"]:
        if pid:
            rows.append((uid, pid, W_FEED_POST * decay(ts), ts))
    for uid, pid, etype, ts in raw["events"]:
        w = W_FEED_VIEW if etype == "feed_view" else W_PLACE_VIEW
        rows.append((uid, pid, w * decay(ts), ts))
    # All-time history at floor weight (ts=None keeps it out of the time-split)
    for uid, pid, count in raw.get("old_checkins", []):
        if pid:
            rows.append((uid, pid, ALL_TIME_FLOOR * min(math.log1p(count) + 1, 3.0), None))
    return rows, coords


def _fit_core(raw: dict, rows: list, coords: dict) -> RecommendationModel:
    """CPU-bound numpy fit over the given interaction rows."""
    m = RecommendationModel()
    m.n_interactions = len(rows)

    for uid, pts in coords.items():
        tot = sum(w for _, _, w in pts)
        if tot > 0:
            m.centroids[uid] = (
                sum(la * w for la, _, w in pts) / tot,
                sum(ln * w for _, ln, w in pts) / tot,
            )

    # ---- venue metadata / indexing ----
    for fk_id, pid, name, address, lat, lng, types_json, bounce_count in raw["places"]:
        try:
            types = set(json.loads(types_json)) if types_json else set()
        except (json.JSONDecodeError, TypeError):
            types = set()
        m.venue_index[pid] = len(m.venue_ids)
        m.venue_ids.append(pid)
        m.venue_meta.append({
            "fk_id": fk_id, "name": name, "address": address,
            "lat": lat, "lng": lng, "types": types,
            "pop": float(bounce_count or 0),
        })

    user_ids = sorted({uid for uid, _, _, _ in rows} |
                      {f for f, _, _ in raw["follows"]} |
                      {g for _, g, _ in raw["follows"]})
    m.user_index = {uid: i for i, uid in enumerate(user_ids)}

    n_u, n_v = len(user_ids), len(m.venue_ids)
    if n_v == 0:
        m.built_at = time.time()
        return m

    R = np.zeros((max(n_u, 1), n_v))
    for uid, pid, w, _ in rows:
        vi = m.venue_index.get(pid)
        ui = m.user_index.get(uid)
        if vi is not None and ui is not None:
            R[ui, vi] += w

    for ui in range(n_u):
        nz = np.nonzero(R[ui])[0]
        if nz.size:
            m.R_sparse[ui] = {int(v): float(R[ui, v]) for v in nz}
    for vi in range(n_v):
        nz = np.nonzero(R[:, vi])[0]
        if nz.size:
            m.venue_visitors[vi] = {user_ids[int(u)]: float(R[u, vi]) for u in nz}

    # ---- 1. ALS matrix factorization ----
    if n_u > 0 and R.sum() > 0:
        m.X, m.Y = _als_implicit(R, MF_FACTORS, MF_ALPHA, MF_REG, MF_ITERS)
    else:
        m.X = np.zeros((max(n_u, 1), 2))
        m.Y = np.zeros((n_v, 2))

    # ---- 2. graph embeddings (follows + co-attendance) ----
    following: dict[int, set] = defaultdict(set)
    close = set()
    for f, g, cf in raw["follows"]:
        following[f].add(g)
        if cf == "accepted":
            close.add((f, g))
    ties: dict[int, dict[int, float]] = defaultdict(dict)
    A = np.zeros((max(n_u, 1), max(n_u, 1)))
    for f, followed in following.items():
        for g in followed:
            mutual = f in following.get(g, set())
            s = TIE_MUTUAL if mutual else TIE_ONE_WAY
            if (f, g) in close or (g, f) in close:
                s = TIE_CLOSE_FRIEND
            ties[f][g] = max(ties[f].get(g, 0.0), s)
            fi, gi = m.user_index.get(f), m.user_index.get(g)
            if fi is not None and gi is not None:
                A[fi, gi] = max(A[fi, gi], s)
                A[gi, fi] = max(A[gi, fi], s)
    m.ties = dict(ties)

    # co-attendance edges: visited the same venue (bounded contribution)
    for vi, visitors in m.venue_visitors.items():
        us = [m.user_index[u] for u in visitors if u in m.user_index]
        if 1 < len(us) <= 30:
            for i in range(len(us)):
                for j in range(i + 1, len(us)):
                    A[us[i], us[j]] += CO_ATTEND_WEIGHT
                    A[us[j], us[i]] += CO_ATTEND_WEIGHT

    m.G = _netmf_embeddings(A, GRAPH_DIM) if n_u > 1 else np.zeros((max(n_u, 1), GRAPH_DIM))

    # venue graph embedding = weighted mean of visitor embeddings
    m.GV = np.zeros((n_v, m.G.shape[1]))
    for vi, visitors in m.venue_visitors.items():
        acc = np.zeros(m.G.shape[1])
        tot = 0.0
        for uid, w in visitors.items():
            ui = m.user_index.get(uid)
            if ui is not None and ui < m.G.shape[0]:
                acc += w * m.G[ui]
                tot += w
        if tot > 0:
            m.GV[vi] = acc / tot

    # ---- 2b. joint random-walk graph for Personalized PageRank ----
    # Nodes = users then venues. Walk flows me -> friends -> their venues ->
    # those venues' other visitors -> THEIR friends/venues -> ... any depth.
    n_total = n_u + n_v
    if n_u > 0 and n_total <= PPR_MAX_NODES:
        W = np.zeros((n_total, n_total), dtype=np.float32)
        W[:n_u, :n_u] = A[:n_u, :n_u]          # user -> user (tie strength)
        W[:n_u, n_u:] = R                       # user -> venue (visit weight)
        W[n_u:, :n_u] = R.T                     # venue -> its visitors
        row_sums = W.sum(axis=1, keepdims=True)
        np.divide(W, row_sums, out=W, where=row_sums > 0)
        m.W_joint = W
    else:
        m.W_joint = None

    # ---- 3. category vectors ----
    m.popularity = np.array([v["pop"] for v in m.venue_meta])
    for ui, venues in m.R_sparse.items():
        vec: dict[str, float] = defaultdict(float)
        for vi, w in venues.items():
            for t in m.venue_meta[vi]["types"]:
                if t not in ("point_of_interest", "establishment"):
                    vec[t] += w
        m.user_cat[ui] = dict(vec)

    # ---- 4. learned ranker on a time split ----
    _train_ranker(m, rows, user_ids)

    m.built_at = time.time()
    logger.info(
        f"Recsys model: {n_u} users, {n_v} venues, "
        f"{len(rows)} interactions, ranker_learned={m.ranker_learned}"
    )
    return m


def _ppr_venue_scores(m: RecommendationModel, user_id: int) -> Optional[np.ndarray]:
    """Personalized PageRank from this user over the joint graph.
    Returns a max-normalized score per venue (the 'network flow' feature)."""
    ui = m.user_index.get(user_id)
    if ui is None or m.W_joint is None:
        return None
    cached = m._ppr_cache.get(user_id)
    if cached is not None:
        return cached
    n_total = m.W_joint.shape[0]
    n_u = len(m.user_index)
    p = np.zeros(n_total, dtype=np.float32)
    e = np.zeros(n_total, dtype=np.float32)
    e[ui] = 1.0
    p[ui] = 1.0
    for _ in range(PPR_ITERS):
        p = (1 - PPR_DAMPING) * e + PPR_DAMPING * (p @ m.W_joint)
    venue_scores = p[n_u:].astype(np.float64)
    peak = venue_scores.max()
    if peak > 0:
        venue_scores = venue_scores / peak
    if len(m._ppr_cache) < 2000:
        m._ppr_cache[user_id] = venue_scores
    return venue_scores


def _features(m: RecommendationModel, uid: int, ui: Optional[int], vi: int,
              origin: Optional[tuple], ppr: Optional[np.ndarray] = None) -> np.ndarray:
    meta = m.venue_meta[vi]
    mf = float(m.X[ui] @ m.Y[vi]) if ui is not None and ui < m.X.shape[0] else 0.0
    graph = float(m.G[ui] @ m.GV[vi]) if ui is not None and ui < m.G.shape[0] else 0.0

    cat = 0.0
    if ui is not None:
        uvec = m.user_cat.get(ui, {})
        if uvec and meta["types"]:
            hit = sum(w for t, w in uvec.items() if t in meta["types"])
            norm = math.sqrt(sum(w * w for w in uvec.values())) * math.sqrt(len(meta["types"]))
            cat = hit / norm if norm > 0 else 0.0

    pop = math.log1p(meta["pop"]) / math.log1p(max(m.popularity.max(), 1.0))

    social = 0.0
    for fid, s in m.ties.get(uid, {}).items():
        w = m.venue_visitors.get(vi, {}).get(fid)
        if w:
            social += s * w
    social = math.tanh(social / 3.0)

    own = m.R_sparse.get(ui, {}).get(vi, 0.0) if ui is not None else 0.0
    novelty = 1.0 / (1.0 + own)

    dist = 0.5
    if origin and meta["lat"] is not None and meta["lng"] is not None:
        d = _haversine_m(origin[0], origin[1], meta["lat"], meta["lng"])
        dist = math.exp(-d / DISTANCE_SCALE_M)

    network_flow = float(ppr[vi]) if ppr is not None and vi < len(ppr) else 0.0

    return np.array([mf, graph, cat, pop, social, novelty, dist, network_flow])


def _train_ranker(m: RecommendationModel, rows: list, user_ids: list):
    """Hold out each user's most recent interactions as positives; sample negatives."""
    by_user: dict[int, list] = defaultdict(list)
    for uid, pid, w, ts in rows:
        if ts is not None and pid in m.venue_index:
            by_user[uid].append((ts, pid))

    rng = np.random.default_rng(11)
    n_v = len(m.venue_ids)
    F, y = [], []
    for uid, items in by_user.items():
        if len(items) < 3:
            continue
        items.sort()
        n_held = max(1, len(items) // 5)
        earlier = items[:-n_held]
        held = items[-n_held:]
        ui = m.user_index.get(uid)
        origin = m.centroids.get(uid)
        ppr = _ppr_venue_scores(m, uid)
        seen = {m.venue_index[pid] for _, pid in items}
        earlier_venues = {m.venue_index[pid] for _, pid in earlier}
        for _, pid in held:
            vi = m.venue_index[pid]
            # Discovery objective: only FIRST visits count as positives,
            # otherwise the ranker learns to predict revisits.
            if vi in earlier_venues:
                continue
            F.append(_features(m, uid, ui, vi, origin, ppr))
            y.append(1.0)
            for _ in range(3):
                nvi = int(rng.integers(0, n_v))
                if nvi not in seen:
                    F.append(_features(m, uid, ui, nvi, origin, ppr))
                    y.append(0.0)

    if sum(y) < MIN_TRAIN_POSITIVES:
        return  # keep default weights

    F = np.array(F)
    y = np.array(y)
    m.feat_mean = F.mean(axis=0)
    m.feat_std = np.maximum(F.std(axis=0), 1e-6)
    Fz = (F - m.feat_mean) / m.feat_std
    m.ranker_w, m.ranker_b = _fit_logistic(Fz, y)
    m.ranker_learned = True


def _evaluate(m_train: RecommendationModel, test_by_user: dict[int, set]) -> Optional[dict]:
    """Recall@10 / MRR on held-out first visits, vs a popularity baseline.
    The eval model was fit WITHOUT these interactions — no leakage."""
    hits, rr, base_hits, n_cases = 0, 0.0, 0, 0
    pop_order = np.argsort(-m_train.popularity)
    for uid, positives in test_by_user.items():
        recs = recommend_for_user(m_train, uid, limit=50)
        rec_ids = [r["place_id"] for r in recs]
        ui = m_train.user_index.get(uid)
        trained_on = set(m_train.R_sparse.get(ui, {}).keys()) if ui is not None else set()
        baseline = [m_train.venue_ids[vi] for vi in pop_order
                    if vi not in trained_on][:10]
        for pid in positives:
            n_cases += 1
            if pid in rec_ids[:10]:
                hits += 1
            if pid in rec_ids:
                rr += 1.0 / (rec_ids.index(pid) + 1)
            if pid in baseline:
                base_hits += 1
    if n_cases < 10:
        return None
    return {
        "test_cases": n_cases,
        "recall_at_10": round(hits / n_cases, 4),
        "mrr_at_50": round(rr / n_cases, 4),
        "popularity_baseline_recall_at_10": round(base_hits / n_cases, 4),
    }


def _fit(raw: dict) -> RecommendationModel:
    """Full fit: honest time-split eval on a train-only model, then the
    production model over all interactions."""
    rows, coords = _build_rows(raw)

    # Per-user time split — most recent first-visits held out for eval
    by_user: dict[int, list] = defaultdict(list)
    for uid, pid, w, ts in rows:
        if ts is not None:
            by_user[uid].append((ts, uid, pid, w))
    test_keys: set = set()
    test_by_user: dict[int, set] = defaultdict(set)
    for uid, items in by_user.items():
        if len(items) < 3:
            continue
        items.sort()
        n_held = max(1, len(items) // 5)
        earlier_pids = {pid for _, _, pid, _ in items[:-n_held]}
        for ts, _, pid, w in items[-n_held:]:
            if pid not in earlier_pids:
                test_keys.add((uid, pid, ts))
                test_by_user[uid].add(pid)

    metrics = None
    if test_by_user:
        train_rows = [r for r in rows if (r[0], r[1], r[3]) not in test_keys]
        try:
            m_train = _fit_core(raw, train_rows, coords)
            metrics = _evaluate(m_train, dict(test_by_user))
        except Exception as e:
            logger.warning(f"Recsys eval failed: {e}")

    m = _fit_core(raw, rows, coords)
    m.metrics = metrics
    if metrics:
        logger.info(f"Recsys eval: {metrics}")
    return m


async def get_model(db: AsyncSession) -> RecommendationModel:
    global _model
    if _model.is_fresh:
        return _model
    async with _model_lock:
        if _model.is_fresh:
            return _model
        raw = await _load_raw(db)
        _model = await asyncio.to_thread(_fit, raw)
        return _model


# ---------------------------------------------------------------- serving


def recommend_for_user(
    m: RecommendationModel,
    user_id: int,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    limit: int = 10,
) -> list[dict]:
    n_v = len(m.venue_ids)
    if n_v == 0:
        return []

    ui = m.user_index.get(user_id)
    origin = (lat, lng) if lat is not None and lng is not None else m.centroids.get(user_id)
    visited = m.R_sparse.get(ui, {}) if ui is not None else {}
    ppr = _ppr_venue_scores(m, user_id)

    # --- candidate generation ---
    candidates: set[int] = set()
    if ui is not None and ui < m.X.shape[0] and m.X[ui].any():
        scores = m.Y @ m.X[ui]
        k = min(CANDIDATE_POOL, n_v)
        candidates |= set(np.argpartition(-scores, k - 1)[:k].tolist())
    for fid in m.ties.get(user_id, {}):
        fui = m.user_index.get(fid)
        if fui is not None:
            candidates |= set(m.R_sparse.get(fui, {}).keys())
    if ppr is not None:
        k = min(PPR_CANDIDATES, n_v)
        candidates |= set(np.argpartition(-ppr, k - 1)[:k].tolist())
    top_pop = np.argsort(-m.popularity)[:limit * 3]
    candidates |= set(top_pop.tolist())

    # Discovery surface: drop anywhere the user has meaningful recent history;
    # long-decayed old favorites (w < 0.5) may resurface.
    heavy = {vi for vi, w in visited.items() if w >= 0.5}
    candidates -= heavy

    # --- rank ---
    scored = []
    for vi in candidates:
        meta = m.venue_meta[vi]
        if meta["types"] & EXCLUDED_TYPES:
            continue
        f = _features(m, user_id, ui, vi, origin, ppr)
        fz = (f - m.feat_mean) / m.feat_std if m.ranker_learned else f
        z = float(fz @ m.ranker_w + m.ranker_b)
        score = 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))
        scored.append((score, vi, f))
    scored.sort(key=lambda t: t[0], reverse=True)

    results = []
    for score, vi, f in scored[:limit]:
        meta = m.venue_meta[vi]
        reasons = _reasons(m, user_id, ui, vi, f)
        distance_m = None
        if origin and meta["lat"] is not None and meta["lng"] is not None:
            distance_m = round(_haversine_m(origin[0], origin[1], meta["lat"], meta["lng"]))
        results.append({
            "place_id": m.venue_ids[vi],
            "places_fk_id": meta["fk_id"],
            "name": meta["name"],
            "address": meta["address"],
            "latitude": meta["lat"],
            "longitude": meta["lng"],
            "distance_m": distance_m,
            "score": round(score, 5),
            "reasons": reasons,
            "friend_count": _friend_count(m, user_id, vi),
        })
    return results


def _friend_count(m: RecommendationModel, user_id: int, vi: int) -> int:
    return sum(1 for fid in m.ties.get(user_id, {}) if fid in m.venue_visitors.get(vi, {}))


def _reasons(m: RecommendationModel, user_id: int, ui: Optional[int], vi: int,
             f: np.ndarray) -> list[str]:
    reasons = []
    n_friends = _friend_count(m, user_id, vi)
    if n_friends > 1:
        reasons.append(f"{n_friends} of your people go here")
    elif n_friends == 1:
        reasons.append("Someone you follow goes here")

    # MF explanation: nearest visited venue in latent space
    if ui is not None and f[0] > 0 and m.R_sparse.get(ui):
        best, best_sim = None, 0.0
        yv = m.Y[vi]
        yv_norm = np.linalg.norm(yv)
        if yv_norm > 0:
            for ovi in m.R_sparse[ui]:
                if ovi == vi:
                    continue
                yo = m.Y[ovi]
                denom = yv_norm * np.linalg.norm(yo)
                if denom > 0:
                    sim = float(yv @ yo) / denom
                    if sim > best_sim:
                        best, best_sim = ovi, sim
        if best is not None and best_sim > 0.3:
            reasons.append(f"Because you go to {m.venue_meta[best]['name']}")

    # Strong network flow with no direct friend = friends-of-friends territory
    if not reasons and f[7] > 0.3:
        reasons.append("Big in your extended network")

    # Resurfaced old favorite (low residual weight — recent visits get filtered out)
    if not reasons and ui is not None and m.R_sparse.get(ui, {}).get(vi, 0.0) > 0:
        reasons.append("An old favorite of yours")

    if f[2] > 0.25:
        reasons.append("Matches your taste")
    if not reasons:
        reasons.append("Popular right now")
    return reasons[:2]


# ---------------------------------------------------------------- event log


def log_place_event(user_id: int, place_id: str, event_type: str):
    """Fire-and-forget weak-signal logging (place_view, feed_view)."""
    async def _log():
        try:
            async with create_async_session() as session:
                session.add(UserPlaceEvent(
                    user_id=user_id, place_id=place_id, event_type=event_type
                ))
                await session.commit()
        except Exception as e:
            logger.debug(f"place event log failed: {e}")
    try:
        asyncio.create_task(_log())
    except RuntimeError:
        pass
