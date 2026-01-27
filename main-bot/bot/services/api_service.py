"""
HTTP client for communicating with api and user-bot services.

This module provides a unified interface to all API services.
"""

import logging
from typing import Optional, Dict, Any
import httpx
from bot.core.config import get_settings

from bot.services.api.users import UserService
from bot.services.api.channels import ChannelService
from bot.services.api.posts import PostService
from bot.services.api.ml import MLService

logger = logging.getLogger(__name__)
settings = get_settings()


class CoreAPIClient:
    """Unified client for api service with all domain services."""
    
    def __init__(self):
        self.users = UserService()
        self.channels = ChannelService()
        self.posts = PostService()
        self.ml = MLService()
    
    async def close(self):
        """Close all service clients."""
        await self.users.close()
        await self.channels.close()
        await self.posts.close()
        await self.ml.close()
    
    # Delegate methods for backward compatibility
    async def get_or_create_user(self, *args, **kwargs):
        """Get or create user with language support."""
        return await self.users.get_or_create_user(*args, **kwargs)
    
    async def get_user(self, *args, **kwargs):
        return await self.users.get_user(*args, **kwargs)
    
    async def update_user(self, *args, **kwargs):
        return await self.users.update_user(*args, **kwargs)
    
    async def update_activity(self, *args, **kwargs):
        return await self.users.update_activity(*args, **kwargs)
    
    async def create_log(self, *args, **kwargs):
        return await self.users.create_log(*args, **kwargs)
    
    async def get_user_language(self, *args, **kwargs):
        return await self.users.get_user_language(*args, **kwargs)
    
    async def set_user_language(self, *args, **kwargs):
        return await self.users.set_user_language(*args, **kwargs)
    
    async def get_feed_users(self, *args, **kwargs):
        return await self.users.get_feed_users(*args, **kwargs)
    
    async def get_default_channels(self, *args, **kwargs):
        return await self.channels.get_default_channels(*args, **kwargs)
    
    async def add_user_channel(self, *args, **kwargs):
        return await self.channels.add_user_channel(*args, **kwargs)
    
    async def get_user_channels(self, *args, **kwargs):
        return await self.channels.get_user_channels(*args, **kwargs)
    
    async def get_user_interactions(self, *args, **kwargs):
        return await self.posts.get_user_interactions(*args, **kwargs)
    
    async def get_training_posts(self, *args, **kwargs):
        return await self.posts.get_training_posts(*args, **kwargs)
    
    async def create_interaction(self, *args, **kwargs):
        return await self.posts.create_interaction(*args, **kwargs)
    
    async def get_best_posts(self, *args, **kwargs):
        return await self.posts.get_best_posts(*args, **kwargs)
    
    async def train_model(self, *args, **kwargs):
        return await self.ml.train_model(*args, **kwargs)
    
    async def check_training_eligibility(self, *args, **kwargs):
        return await self.ml.check_training_eligibility(*args, **kwargs)
    
    async def get_recommendations(self, *args, **kwargs):
        return await self.ml.get_recommendations(*args, **kwargs)


class UserBotClient:
    """Client for user-bot service (scraper)."""
    
    def __init__(self):
        self.base_url = settings.user_bot_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=60.0)
    
    async def close(self):
        await self.client.aclose()
    
    async def scrape_channel(
        self,
        channel_username: str,
        limit: int = 7
    ) -> Optional[Dict[str, Any]]:
        """Trigger channel scraping."""
        try:
            response = await self.client.post(
                f"{self.base_url}/cmd/scrape",
                json={
                    "channel_username": channel_username,
                    "limit": limit,
                }
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error scraping channel {channel_username}: {e}")
            return None
    
    async def join_channel(self, channel_username: str) -> Optional[Dict[str, Any]]:
        """Request user-bot to join a channel."""
        try:
            response = await self.client.post(
                f"{self.base_url}/cmd/join",
                json={"channel_username": channel_username}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error joining channel {channel_username}: {e}")
            return None
    
    async def get_photo(self, channel_username: str, message_id: int) -> Optional[bytes]:
        """Fetch photo bytes for a specific channel message from user-bot."""
        try:
            response = await self.client.get(
                f"{self.base_url}/media/photo",
                params={
                    "channel_username": channel_username,
                    "message_id": message_id,
                },
            )
            if response.status_code == 200:
                return response.content
            return None
        except Exception as e:
            logger.error(f"Error fetching photo for {channel_username}#{message_id}: {e}")
            return None

    async def get_video(self, channel_username: str, message_id: int) -> Optional[bytes]:
        """Fetch video bytes for a specific channel message from user-bot."""
        try:
            response = await self.client.get(
                f"{self.base_url}/media/video",
                params={
                    "channel_username": channel_username,
                    "message_id": message_id,
                },
                timeout=30.0,  # Reasonable timeout for videos, skip if too large
            )
            if response.status_code == 200:
                return response.content
            return None
        except Exception as e:
            logger.error(f"Error fetching video for {channel_username}#{message_id}: {e}")
            return None
    
    async def health_check(self) -> bool:
        """Check if user-bot is healthy."""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False


# Singleton instances
_core_api_client: Optional[CoreAPIClient] = None
_user_bot_client: Optional[UserBotClient] = None


def get_core_api() -> CoreAPIClient:
    global _core_api_client
    if _core_api_client is None:
        _core_api_client = CoreAPIClient()
    return _core_api_client


def get_user_bot() -> UserBotClient:
    global _user_bot_client
    if _user_bot_client is None:
        _user_bot_client = UserBotClient()
    return _user_bot_client


async def close_clients():
    global _core_api_client, _user_bot_client
    if _core_api_client:
        await _core_api_client.close()
    if _user_bot_client:
        await _user_bot_client.close()
