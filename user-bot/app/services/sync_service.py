"""
Service for syncing data to Core API.
"""
import logging
from typing import Optional, List
import httpx

from app.core.config import get_settings
from app.types import PostDataDict, SyncServiceProtocol

logger = logging.getLogger(__name__)
settings = get_settings()


class SyncService:
    """Service for syncing channels and posts to Core API."""
    
    def __init__(self, core_api_url: Optional[str] = None):
        """
        Initialize sync service.
        
        Args:
            core_api_url: Core API URL (defaults to settings.core_api_url)
        """
        self.core_api_url = core_api_url or settings.core_api_url
    
    async def sync_channel(
        self,
        channel_telegram_id: int,
        channel_username: str,
        channel_title: str
    ) -> bool:
        """
        Sync channel data to core API.
        
        Args:
            channel_telegram_id: Telegram channel ID
            channel_username: Channel username
            channel_title: Channel title
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.core_api_url}/api/v1/channels/",
                    json={
                        "telegram_id": channel_telegram_id,
                        "username": channel_username,
                        "title": channel_title,
                        "is_default": False,
                    }
                )
                return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Failed to sync channel to core API: {e}")
            return False
    
    async def sync_posts(
        self,
        channel_telegram_id: int,
        posts: List[PostDataDict]
    ) -> bool:
        """
        Sync posts to core API.
        
        Args:
            channel_telegram_id: Telegram channel ID
            posts: List of post data dictionaries
            
        Returns:
            True if successful, False otherwise
        """
        if not posts:
            return True
        
        try:
            post_data = []
            for post in posts:
                post_data.append({
                    "telegram_message_id": post["telegram_message_id"],
                    "text": post.get("text"),
                    "media_type": post.get("media_type"),
                    "media_file_id": post.get("media_file_id"),
                    "posted_at": post["posted_at"],
                })
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.core_api_url}/api/v1/posts/bulk",
                    json={
                        "channel_telegram_id": channel_telegram_id,
                        "posts": post_data,
                    }
                )
                return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Failed to sync posts to core API: {e}")
            return False
    
    async def sync_realtime_post(
        self,
        channel_id: int,
        channel_username: str,
        channel_title: str,
        post_data: PostDataDict
    ) -> Optional[int]:
        """
        Sync a single post to core-api. Returns the created post_id.
        
        Args:
            channel_id: Telegram channel ID
            channel_username: Channel username
            channel_title: Channel title
            post_data: Post data dictionary
            
        Returns:
            Created post ID or None if failed
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Ensure channel exists
                await client.post(
                    f"{self.core_api_url}/api/v1/channels/",
                    json={
                        "telegram_id": channel_id,
                        "username": channel_username,
                        "title": channel_title,
                        "is_default": False,
                    }
                )
                
                # Create post
                response = await client.post(
                    f"{self.core_api_url}/api/v1/posts/bulk",
                    json={
                        "channel_telegram_id": channel_id,
                        "posts": [post_data],
                    }
                )
                
                # Try to get post_id from response
                if response.status_code == 201:
                    data = response.json()
                    if data and "post_ids" in data and len(data["post_ids"]) > 0:
                        return data["post_ids"][0]
                return None
        except Exception as e:
            logger.error(f"Failed to sync real-time post: {e}")
            return None

