from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
import logging

from db.database import get_async_session
from db.models import FeaturedPlace, Place, GooglePic, User
from api.dependencies import get_current_user

router = APIRouter(prefix="/places", tags=["featured-places"])
logger = logging.getLogger(__name__)


class FeaturedPlaceResponse(BaseModel):
    place_id: str          # Google Places ID
    name: str
    address: Optional[str]
    latitude: float
    longitude: float
    photo_url: Optional[str]
    city: str
    rank: int


@router.get("/featured", response_model=List[FeaturedPlaceResponse])
async def get_featured_places(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    All active hand-picked featured places across launch cities.
    The client renders whichever fall inside the viewport, so no
    server-side geo filtering is needed (the list is tiny).
    """
    result = await db.execute(
        select(FeaturedPlace, Place)
        .join(Place, FeaturedPlace.place_fk_id == Place.id)
        .where(FeaturedPlace.is_active == True)
        .order_by(FeaturedPlace.city, FeaturedPlace.rank, FeaturedPlace.id)
    )
    rows = result.all()

    # First photo per place, one query
    photos = {}
    place_fk_ids = [place.id for _, place in rows]
    if place_fk_ids:
        photo_result = await db.execute(
            select(GooglePic.place_id, GooglePic.photo_url)
            .where(GooglePic.place_id.in_(place_fk_ids), GooglePic.photo_url.isnot(None))
            .order_by(GooglePic.id)
        )
        for fk_id, url in photo_result.all():
            photos.setdefault(fk_id, url)

    return [
        FeaturedPlaceResponse(
            place_id=place.place_id,
            name=place.name,
            address=place.address,
            latitude=place.latitude,
            longitude=place.longitude,
            photo_url=photos.get(place.id),
            city=featured.city,
            rank=featured.rank,
        )
        for featured, place in rows
    ]
