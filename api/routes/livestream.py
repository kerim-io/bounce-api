# from fastapi import APIRouter, Depends, HTTPException, Header
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select, update
# from typing import List, Optional
# from datetime import datetime, timezone
# import logging
# import aiohttp
# import asyncio
# import os
#
# from db.database import get_async_session
# from db.models import User, Livestream
# from services.auth_service import decode_token
# from pydantic import BaseModel
#
# router = APIRouter(prefix="/livestream", tags=["livestream"])
# logger = logging.getLogger(__name__)
#
# MEDIA_SERVER_URL = os.getenv("MEDIA_SERVER_URL", "http://localhost:9001")
# MEDIA_SERVER_WS_URL = os.getenv("MEDIA_SERVER_WS_URL", "ws://localhost:9002")
#
# # Health check cache to prevent log spam
# _media_server_health = {
#     "available": True,
#     "last_check": 0,
#     "check_interval": 30  # Only retry every 30 seconds when down
# }
#
#
# class LiveUserResponse(BaseModel):
#     id: int
#     user_id: int
#     username: str
#     room_id: str
#     profile_pic_url: str | None
#
#     class Config:
#         from_attributes = True
#
#
# @router.get("/active", response_model=List[LiveUserResponse])
# async def get_active_livestreams(
#     db: AsyncSession = Depends(get_async_session)
# ):
#     """
#     Get all currently active livestreams from any user (not just followed users).
#     """
#     try:
#         # Call the media server to get active rooms
#         async with aiohttp.ClientSession() as session:
#             try:
#                 async with session.get(f"{MEDIA_SERVER_URL}/stats", timeout=aiohttp.ClientTimeout(total=2)) as resp:
#                     if resp.status != 200:
#                         logger.warning("Media server returned non-200 status, returning empty list")
#                         return []
#
#                     stats = await resp.json()
#                     active_rooms = stats.get("rooms", [])
#
#                     if not active_rooms:
#                         return []
#
#                     # Get user info for each active room
#                     live_users = []
#                     for room in active_rooms:
#                         room_id = room.get("room_id")
#                         host_id = room.get("host_id")
#
#                         if not host_id:
#                             continue
#
#                         # Get user from database
#                         result = await db.execute(select(User).where(User.id == host_id))
#                         user = result.scalar_one_or_none()
#
#                         if user:
#                             live_users.append(LiveUserResponse(
#                                 id=user.id,
#                                 user_id=user.id,
#                                 username=user.nickname or user.username or user.email or f"user_{user.id}",
#                                 room_id=room_id,
#                                 profile_pic_url=user.profile_picture
#                             ))
#
#                     return live_users
#             except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
#                 logger.warning(f"Media server unavailable: {str(e)}")
#                 return []
#     except Exception as e:
#         logger.error("Error fetching active livestreams", exc_info=True, extra={"error": str(e)})
#         return []
#
#
# class StartStreamResponse(BaseModel):
#     room_id: str
#     websocket_url: str
#
#
# @router.post("/start", response_model=StartStreamResponse)
# async def start_livestream(
#     authorization: Optional[str] = Header(None),
#     db: AsyncSession = Depends(get_async_session)
# ):
#     """
#     Start a new livestream. Creates a room on the media server.
#     """
#     if not authorization or not authorization.startswith("Bearer "):
#         raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
#
#     token = authorization.split(" ")[1]
#
#     try:
#         payload = decode_token(token)
#         user_id = int(payload.get("sub"))
#     except Exception as e:
#         raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
#
#     try:
#         async with aiohttp.ClientSession() as session:
#             payload = {
#                 "post_id": f"post_{user_id}",
#                 "host_user_id": str(user_id)
#             }
#
#             try:
#                 async with session.post(
#                     f"{MEDIA_SERVER_URL}/room/create",
#                     headers={"Authorization": authorization},
#                     json=payload,
#                     timeout=aiohttp.ClientTimeout(total=5)
#                 ) as resp:
#                     if resp.status != 201:
#                         text = await resp.text()
#                         raise HTTPException(status_code=resp.status, detail=f"Media server error: {text}")
#
#                     data = await resp.json()
#                     room_id = data.get("room_id")
#
#                     if not room_id:
#                         raise HTTPException(status_code=500, detail="No room_id returned from media server")
#
#                     # Save livestream to database
#                     livestream = Livestream(
#                         user_id=user_id,
#                         room_id=room_id,
#                         post_id=f"post_{user_id}",
#                         status='active'
#                     )
#                     db.add(livestream)
#                     await db.commit()
#                     await db.refresh(livestream)
#
#                     logger.info(
#                         "Livestream started",
#                         extra={"user_id": user_id, "room_id": room_id, "livestream_id": livestream.id}
#                     )
#
#                     websocket_url = f"{MEDIA_SERVER_WS_URL}/room/{room_id}/host"
#
#                     return StartStreamResponse(
#                         room_id=room_id,
#                         websocket_url=websocket_url
#                     )
#             except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
#                 logger.error(f"Cannot connect to media server: {str(e)}")
#                 raise HTTPException(status_code=503, detail=f"Cannot connect to media server: {str(e)}")
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error("Error starting livestream", exc_info=True, extra={"error": str(e)})
#         raise HTTPException(status_code=500, detail="Failed to start livestream")
#
#
# class StopStreamResponse(BaseModel):
#     status: str
#     room_id: str
#
#
# @router.post("/stop/{room_id}", response_model=StopStreamResponse)
# async def stop_livestream(
#     room_id: str,
#     authorization: Optional[str] = Header(None),
#     db: AsyncSession = Depends(get_async_session)
# ):
#     """
#     Stop an active livestream.
#     """
#     if not authorization or not authorization.startswith("Bearer "):
#         raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
#
#     token = authorization.split(" ")[1]
#
#     try:
#         payload = decode_token(token)
#         user_id = int(payload.get("sub"))
#     except Exception as e:
#         raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
#
#     try:
#         # Get livestream from database
#         result = await db.execute(
#             select(Livestream).where(
#                 Livestream.room_id == room_id,
#                 Livestream.status == 'active'
#             )
#         )
#         livestream = result.scalar_one_or_none()
#
#         if not livestream:
#             raise HTTPException(status_code=404, detail="Active livestream not found")
#
#         # Verify ownership
#         if livestream.user_id != user_id:
#             raise HTTPException(status_code=403, detail="You can only stop your own livestreams")
#
#         # Update livestream in database
#         livestream.ended_at = datetime.now(timezone.utc)
#         livestream.status = 'ended'
#         await db.commit()
#
#         duration = livestream.duration_seconds
#         logger.info(
#             "Livestream ended",
#             extra={
#                 "room_id": room_id,
#                 "duration_seconds": duration,
#                 "max_viewers": livestream.max_viewers
#             }
#         )
#
#         # Stop room on media server (best effort - don't fail if media server is down)
#         try:
#             async with aiohttp.ClientSession() as session:
#                 async with session.post(
#                     f"{MEDIA_SERVER_URL}/room/{room_id}/stop",
#                     headers={"Authorization": authorization},
#                     timeout=aiohttp.ClientTimeout(total=5)
#                 ) as resp:
#                     if resp.status != 200:
#                         text = await resp.text()
#                         logger.warning(f"Media server returned error when stopping room: {text}")
#         except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
#             # Log but don't fail - livestream already marked as ended in DB
#             logger.warning(f"Could not notify media server of room stop: {str(e)}")
#
#         return StopStreamResponse(
#             status="stopped",
#             room_id=room_id
#         )
#     except HTTPException:
#         await db.rollback()
#         raise
#     except Exception as e:
#         await db.rollback()
#         logger.error("Error stopping livestream", exc_info=True, extra={"error": str(e)})
#         raise HTTPException(status_code=500, detail="Failed to stop livestream")
