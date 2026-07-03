"""Stable, cacheable image endpoints.

GET /img/place/{places_fk_id}        first venue photo
GET /img/place/{places_fk_id}/{n}    nth venue photo (0-4)
GET /img/user/{user_id}              profile picture

Why this exists:
- Google photo URLs previously shipped to clients with the API key embedded;
  here the key stays server-side and clients get stable URLs they can cache.
- Base64 profile pictures stored in Postgres become real images addressable
  by URL, so client-side caches finally work for them.
- Bytes are cached in Redis (binary client) and served with ETag/304 and a
  long Cache-Control, so repeat loads cost nothing.

Endpoints are public by design — image URLs are fetched by clients without
auth headers (same exposure as the existing /bounce/img-proxy).
"""

import base64
import hashlib
import logging
from typing import Callable, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.database import get_async_session
from db.models import GooglePic, User
from services.redis import circuit_is_open, get_redis_binary

router = APIRouter(prefix="/img", tags=["images"])
logger = logging.getLogger(__name__)

IMG_TTL = 7 * 24 * 3600
MAX_IMAGE_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 10.0


async def _cache_get(key: str) -> tuple[Optional[bytes], Optional[str]]:
    if circuit_is_open():
        return None, None
    try:
        redis = await get_redis_binary()
        pipe = redis.pipeline()
        pipe.get(f"imgbytes:{key}")
        pipe.get(f"imgct:{key}")
        data, ct = await pipe.execute()
        if data:
            return data, (ct.decode() if ct else "image/jpeg")
    except Exception as e:
        logger.warning(f"Image cache read failed: {e}")
    return None, None


async def _cache_set(key: str, data: bytes, content_type: str):
    if circuit_is_open():
        return
    try:
        redis = await get_redis_binary()
        pipe = redis.pipeline()
        pipe.setex(f"imgbytes:{key}", IMG_TTL, data)
        pipe.setex(f"imgct:{key}", IMG_TTL, content_type)
        await pipe.execute()
    except Exception as e:
        logger.warning(f"Image cache write failed: {e}")


async def _fetch_remote(url: str) -> tuple[Optional[bytes], Optional[str]]:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=FETCH_TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None, None
            content_type = resp.headers.get("content-type", "image/jpeg")
            if not content_type.startswith("image/"):
                return None, None
            if len(resp.content) > MAX_IMAGE_BYTES:
                return None, None
            return resp.content, content_type
    except Exception as e:
        logger.warning(f"Image fetch failed for {url[:80]}: {e}")
        return None, None


def _parse_data_uri(uri: str) -> tuple[Optional[bytes], Optional[str]]:
    try:
        header, b64 = uri.split(",", 1)
        content_type = "image/jpeg"
        if header.startswith("data:") and ";" in header:
            content_type = header[5:].split(";")[0] or "image/jpeg"
        return base64.b64decode(b64), content_type
    except Exception:
        return None, None


async def _serve(request: Request, cache_key: str, resolve) -> Response:
    """Cache -> resolve -> ETag/304 -> long-lived response."""
    data, content_type = await _cache_get(cache_key)
    if data is None:
        data, content_type = await resolve()
        if data is None:
            raise HTTPException(status_code=404, detail="Image not found")
        await _cache_set(cache_key, data, content_type or "image/jpeg")

    etag = f'W/"{hashlib.sha1(data).hexdigest()[:20]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    return Response(
        content=data,
        media_type=content_type or "image/jpeg",
        headers={
            "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
            "ETag": etag,
        },
    )


@router.get("/place/{places_fk_id}")
@router.get("/place/{places_fk_id}/{n}")
async def get_place_image(
    places_fk_id: int,
    request: Request,
    n: int = 0,
    db: AsyncSession = Depends(get_async_session),
):
    """Nth photo of a venue. Google API key stays server-side."""
    if not 0 <= n <= 4:
        raise HTTPException(status_code=404, detail="Image not found")

    async def resolve():
        result = await db.execute(
            select(GooglePic)
            .where(GooglePic.place_id == places_fk_id)
            .order_by(GooglePic.id)
            .offset(n)
            .limit(1)
        )
        pic = result.scalar_one_or_none()
        if not pic:
            return None, None
        url = pic.photo_url
        if not url and pic.photo_reference and settings.GOOGLE_MAPS_API_KEY:
            url = (
                f"https://maps.googleapis.com/maps/api/place/photo"
                f"?maxwidth=800&photo_reference={pic.photo_reference}"
                f"&key={settings.GOOGLE_MAPS_API_KEY}"
            )
        if not url or not url.startswith("http"):
            return None, None
        return await _fetch_remote(url)

    return await _serve(request, f"place:{places_fk_id}:{n}", resolve)


@router.get("/user/{user_id}")
async def get_user_image(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Profile picture as a real, cacheable image — whether it's stored as a
    base64 data URI, a relative upload path, or a remote URL."""

    async def resolve():
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None, None
        pic = (
            user.profile_picture_1
            or user.profile_picture
            or user.instagram_profile_pic
        )
        if not pic:
            return None, None
        if pic.startswith("data:"):
            return _parse_data_uri(pic)
        if pic.startswith("http"):
            return await _fetch_remote(pic)
        return None, None

    return await _serve(request, f"user:{user_id}", resolve)
