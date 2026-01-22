"""User service for API interactions."""

import logging
from typing import Optional, List, Dict, Any
from .base import BaseAPIClient

logger = logging.getLogger(__name__)


class UserService(BaseAPIClient):
    """Service for user-related API endpoints."""
    
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

