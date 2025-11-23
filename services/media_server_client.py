"""
Python client for communicating with the C++ media server.
Handles room creation, deletion, and statistics retrieval for BitBasel media streaming.
"""

import httpx
import logging
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class MediaServerClient:
    """Client for interacting with the C++ WebRTC media server."""

    def __init__(self, base_url: str = "http://localhost:8082", timeout: float = 10.0):
        """
        Initialize the media server client.

        Args:
            base_url: Base URL of the C++ media server
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def health_check(self) -> bool:
        """
        Check if the media server is healthy and reachable.

        Returns:
            True if server is healthy, False otherwise
        """
        try:
            response = await self.client.get(f"{self.base_url}/health")
            if response.status_code == 200:
                data = response.json()
                return data.get("status") == "healthy"
            return False
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return False

    async def create_room(self, post_id: str, host_user_id: str) -> Optional[str]:
        """
        Create a new streaming room in the media server for a post.

        Args:
            post_id: ID of the post with media
            host_user_id: ID of the user posting

        Returns:
            Room ID if successful, None otherwise
        """
        try:
            payload = {
                "post_id": post_id,
                "host_user_id": host_user_id
            }

            response = await self.client.post(
                f"{self.base_url}/room/create",
                json=payload
            )

            if response.status_code == 201:
                data = response.json()
                room_id = data.get("room_id")
                logger.info(f"Created room {room_id} for post {post_id}")
                return room_id
            else:
                logger.error(f"Failed to create room: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error creating room: {str(e)}")
            return None

    async def stop_room(self, room_id: str) -> bool:
        """
        Stop a streaming room and disconnect all participants.

        Args:
            room_id: ID of the room to stop

        Returns:
            True if successful, False otherwise
        """
        try:
            response = await self.client.post(f"{self.base_url}/room/{room_id}/stop")

            if response.status_code == 200:
                logger.info(f"Stopped room {room_id}")
                return True
            else:
                logger.error(f"Failed to stop room: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error stopping room: {str(e)}")
            return False

    async def get_room_stats(self, room_id: str) -> Optional[Dict]:
        """
        Get statistics for a specific room.

        Args:
            room_id: ID of the room

        Returns:
            Dictionary with room stats or None if failed
        """
        try:
            response = await self.client.get(f"{self.base_url}/room/{room_id}/stats")

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get room stats: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error getting room stats: {str(e)}")
            return None

    async def get_server_stats(self) -> Optional[Dict]:
        """
        Get overall media server statistics.

        Returns:
            Dictionary with server stats or None if failed
        """
        try:
            response = await self.client.get(f"{self.base_url}/stats")

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get server stats: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error getting server stats: {str(e)}")
            return None


# Global client instance
_media_server_client: Optional[MediaServerClient] = None


def get_media_server_client() -> MediaServerClient:
    """Get or create the global media server client instance."""
    global _media_server_client

    if _media_server_client is None:
        _media_server_client = MediaServerClient()

    return _media_server_client


async def close_media_server_client():
    """Close the global media server client."""
    global _media_server_client

    if _media_server_client is not None:
        await _media_server_client.close()
        _media_server_client = None
