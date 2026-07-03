from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.routes.bounces import get_venue_photos_batch
from db.database import get_async_session
from db.models import User
from services.recommendations import get_model, recommend_for_user

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


@router.get("/for-you")
async def get_for_you(
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    limit: int = Query(10, ge=1, le=25),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Personalized place suggestions: co-visitation CF + network propagation
    + category affinity + popularity, distance-decayed from the user's
    location (or their activity centroid when no location is passed)."""
    model = await get_model(db)
    suggestions = recommend_for_user(model, current_user.id, lat=lat, lng=lng, limit=limit)

    # Attach photos in one batch query
    fk_ids = [s["places_fk_id"] for s in suggestions if s.get("places_fk_id")]
    photos = await get_venue_photos_batch(db, fk_ids)
    for s in suggestions:
        s["photo_url"] = photos.get(s.pop("places_fk_id"))

    return {"suggestions": suggestions}


@router.get("/model-info")
async def get_model_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Model diagnostics: offline eval metrics (recall@10 / MRR vs popularity
    baseline on a leakage-free time split) and fit stats."""
    model = await get_model(db)
    return {
        "built_at": model.built_at,
        "users": len(model.user_index),
        "venues": len(model.venue_ids),
        "interactions": model.n_interactions,
        "ranker_learned": model.ranker_learned,
        "network_walk_enabled": model.W_joint is not None,
        "eval": model.metrics,
    }
