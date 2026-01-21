"""
HTTP client for communicating with api and user-bot services.
"""

import logging
from typing import Optional, List, Dict, Any
import httpx
from bot.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class CoreAPIClient:
    """Client for api service."""
    
    def __init__(self):
        self.base_url = settings.core_api_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        await self.client.aclose()
    
    # ============== User Endpoints ==============
    
    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get or create a user."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/users/",
                json={
                    "telegram_id": telegram_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                }
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting/creating user: {e}")
            return None
    
    async def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user by telegram ID."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/users/{telegram_id}"
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    async def update_user(
        self,
        telegram_id: int,
        status: Optional[str] = None,
        is_trained: Optional[bool] = None,
        bonus_channels_count: Optional[int] = None,
        initial_best_post_sent: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update user fields."""
        try:
            data = {}
            if status:
                data["status"] = status
            if is_trained is not None:
                data["is_trained"] = is_trained
            if bonus_channels_count is not None:
                data["bonus_channels_count"] = bonus_channels_count
            if initial_best_post_sent is not None:
                data["initial_best_post_sent"] = initial_best_post_sent
            
            response = await self.client.patch(
                f"{self.base_url}/api/v1/users/{telegram_id}",
                json=data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error updating user: {e}")
            return None
    
    async def update_activity(self, telegram_id: int) -> bool:
        """Update user's last activity timestamp."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/users/activity",
                json={"telegram_id": telegram_id}
            )
            return response.status_code == 204
        except Exception as e:
            logger.error(f"Error updating activity: {e}")
            return False
    
    async def create_log(
        self,
        telegram_id: int,
        action: str,
        details: Optional[str] = None
    ) -> bool:
        """Create a user activity log."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/users/logs",
                json={
                    "user_telegram_id": telegram_id,
                    "action": action,
                    "details": details,
                }
            )
            return response.status_code == 201
        except Exception as e:
            logger.error(f"Error creating log: {e}")
            return False
    
    async def get_user_language(self, telegram_id: int) -> str:
        """Get user's preferred language. Defaults to 'en_US'."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/users/{telegram_id}/language"
            )
            if response.status_code == 200:
                return response.json().get("language", "en_US")
            return "en_US"
        except Exception as e:
            logger.error(f"Error getting user language: {e}")
            return "en_US"
    
    async def set_user_language(self, telegram_id: int, language: str) -> bool:
        """Set user's preferred language."""
        try:
            response = await self.client.put(
                f"{self.base_url}/api/v1/users/{telegram_id}/language",
                json={"language": language}
            )
            return response.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Error setting user language: {e}")
            return False
    
    async def get_feed_users(self) -> List[Dict[str, Any]]:
        """Get users eligible for automatic feed delivery (trained or active)."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/users/feed-targets"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting feed users: {e}")
            return []
    
    # ============== Channel Endpoints ==============
    
    async def get_default_channels(self) -> List[Dict[str, Any]]:
        """Get default training channels."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/channels/defaults"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting default channels: {e}")
            return []
    
    async def add_user_channel(
        self,
        telegram_id: int,
        channel_username: str,
        is_for_training: bool = False,
        is_bonus: bool = False
    ) -> bool:
        """Add a channel to user's list."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/channels/user-channel",
                json={
                    "user_telegram_id": telegram_id,
                    "channel_username": channel_username,
                    "is_for_training": is_for_training,
                    "is_bonus": is_bonus,
                }
            )
            return response.status_code == 201
        except Exception as e:
            logger.error(f"Error adding user channel: {e}")
            return False
    
    async def get_user_channels(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Get all channels for a user."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/channels/user/{telegram_id}"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting user channels: {e}")
            return []
    
    async def get_user_interactions(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Get all interactions for a user."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/posts/interactions/{telegram_id}"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting user interactions: {e}")
            return []
    
    # ============== Post Endpoints ==============
    
    async def get_training_posts(
        self,
        telegram_id: int,
        channel_usernames: List[str],
        posts_per_channel: int = 7
    ) -> List[Dict[str, Any]]:
        """Get posts for training."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/posts/training",
                json={
                    "user_telegram_id": telegram_id,
                    "channel_usernames": channel_usernames,
                    "posts_per_channel": posts_per_channel,
                }
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting training posts: {e}")
            return []
    
    async def create_interaction(
        self,
        telegram_id: int,
        post_id: int,
        interaction_type: str
    ) -> bool:
        """Create a user interaction with a post."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/posts/interactions",
                json={
                    "user_telegram_id": telegram_id,
                    "post_id": post_id,
                    "interaction_type": interaction_type,
                }
            )
            return response.status_code == 201
        except Exception as e:
            logger.error(f"Error creating interaction: {e}")
            return False
    
    async def get_best_posts(
        self,
        telegram_id: int,
        limit: int = 1
    ) -> List[Dict[str, Any]]:
        """Get best posts for user feed."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/posts/best",
                json={
                    "user_telegram_id": telegram_id,
                    "limit": limit,
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("posts", [])
        except Exception as e:
            logger.error(f"Error getting best posts: {e}")
            return []
    
    # ============== ML Endpoints ==============
    
    async def train_model(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Trigger model training for user."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/ml/train",
                json={"user_telegram_id": telegram_id},
                timeout=60.0  # Training can take a while
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error training model: {e}")
            return None
    
    async def check_training_eligibility(
        self,
        telegram_id: int
    ) -> tuple[bool, str]:
        """Check if user is eligible for training."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/ml/eligibility/{telegram_id}"
            )
            response.raise_for_status()
            data = response.json()
            return data.get("eligible", False), data.get("message", "")
        except Exception as e:
            logger.error(f"Error checking eligibility: {e}")
            return False, str(e)
    
    async def get_recommendations(
        self,
        telegram_id: int,
        limit: int = 10,
        exclude_interacted: bool = True
    ) -> List[Dict[str, Any]]:
        """Get personalized post recommendations for a user."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/ml/recommendations",
                json={
                    "user_telegram_id": telegram_id,
                    "limit": limit,
                    "exclude_interacted": exclude_interacted,
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("recommendations", [])
        except Exception as e:
            logger.error(f"Error getting recommendations: {e}")
            return []


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
