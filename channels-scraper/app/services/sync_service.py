"""
Sync channels and posts to Core API (same contract as user-bot).
Web-scraper uses pseudo telegram_id from channel username (no real Telegram ID).
"""
import logging
from typing import Optional, List, Dict, Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def pseudo_telegram_id(channel_username: str) -> int:
    """Deterministic pseudo Telegram channel ID from username (no real Telegram ID in web-scraper)."""
    username = (channel_username or "").lstrip("@").strip().lower()
    h = abs(hash(username)) % (10**12)
    return -1000000000000 - h


class SyncService:
    """Sync channels and posts to Core API."""

    def __init__(self, core_api_url: Optional[str] = None):
        self.core_api_url = (core_api_url or settings.core_api_url).rstrip("/")

    async def sync_channel(
        self,
        channel_telegram_id: int,
        channel_username: str,
        channel_title: str,
    ) -> bool:
        """Create or update channel in Core API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.core_api_url}/api/v1/channels/",
                    json={
                        "telegram_id": channel_telegram_id,
                        "username": channel_username,
                        "title": channel_title,
                        "is_default": False,
                    },
                )
                return response.status_code in (200, 201)
        except Exception as e:
            logger.error("Failed to sync channel to core API: %s", e)
            return False

    async def sync_posts(
        self,
        channel_telegram_id: int,
        posts: List[Dict[str, Any]],
        for_training: bool = False,
    ) -> bool:
        """Sync posts to Core API. Each post dict must have telegram_message_id, text, media_type, posted_at."""
        if not posts:
            return True
        try:
            post_data = []
            for p in posts:
                post_data.append({
                    "telegram_message_id": p["telegram_message_id"],
                    "text": p.get("text"),
                    "media_type": p.get("media_type"),
                    "posted_at": p["posted_at"],
                })
            payload = {
                "channel_telegram_id": channel_telegram_id,
                "posts": post_data,
                "for_training": for_training,
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.core_api_url}/api/v1/posts/bulk",
                    json=payload,
                )
                return response.status_code in (200, 201)
        except Exception as e:
            logger.error("Failed to sync posts to core API: %s", e)
            return False

    async def sync_realtime_post(
        self,
        channel_id: int,
        channel_username: str,
        channel_title: str,
        post_data: Dict[str, Any],
    ) -> Optional[int]:
        """Sync a single new post; return created post_id from API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self.core_api_url}/api/v1/channels/",
                    json={
                        "telegram_id": channel_id,
                        "username": channel_username,
                        "title": channel_title,
                        "is_default": False,
                    },
                )
                payload = {
                    "channel_telegram_id": channel_id,
                    "posts": [{
                        "telegram_message_id": post_data["telegram_message_id"],
                        "text": post_data.get("text"),
                        "media_type": post_data.get("media_type"),
                        "posted_at": post_data["posted_at"],
                    }],
                }
                response = await client.post(
                    f"{self.core_api_url}/api/v1/posts/bulk",
                    json=payload,
                )
                if response.status_code == 201:
                    data = response.json()
                    if data and "post_ids" in data and data["post_ids"]:
                        return data["post_ids"][0]
                return None
        except Exception as e:
            logger.error("Failed to sync real-time post: %s", e)
            return None

    async def upload_channel_avatar(
        self, channel_telegram_id: int, avatar_bytes: bytes
    ) -> bool:
        """Upload channel avatar image to API."""
        if not avatar_bytes:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.core_api_url}/api/v1/channels/by-telegram-id/{channel_telegram_id}/avatar",
                    content=avatar_bytes,
                    headers={"Content-Type": "image/jpeg"},
                )
                return response.status_code == 204
        except Exception as e:
            logger.error("Failed to upload channel avatar: %s", e)
            return False

    async def set_channel_description(
        self, channel_telegram_id: int, description: Optional[str]
    ) -> bool:
        """Set channel description in API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.patch(
                    f"{self.core_api_url}/api/v1/channels/by-telegram-id/{channel_telegram_id}/description",
                    json={"description": description},
                )
                return response.status_code == 204
        except Exception as e:
            logger.error("Failed to set channel description: %s", e)
            return False

    async def list_channels(self, skip: int = 0, limit: int = 500) -> List[Dict[str, Any]]:
        """Get list of channels from Core API for polling (returns id, telegram_id, username, title)."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.core_api_url}/api/v1/channels/",
                    params={"skip": skip, "limit": limit},
                )
                if response.status_code != 200:
                    return []
                return response.json()
        except Exception as e:
            logger.error("Failed to list channels: %s", e)
            return []
