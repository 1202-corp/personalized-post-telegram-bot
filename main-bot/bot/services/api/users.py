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
        last_name: Optional[str] = None,
        language_code: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get or create a user.
        
        Args:
            telegram_id: Telegram user ID
            username: Telegram username
            first_name: User's first name
            last_name: User's last name
            language_code: Telegram language code (e.g., "ru", "en") - will be converted to locale
        """
        from bot.core.i18n import normalize_telegram_language, get_supported_languages, get_default_language
        
        # Convert Telegram language_code to locale if provided
        language = None
        if language_code:
            supported = get_supported_languages()
            default = get_default_language()
            language = normalize_telegram_language(language_code, supported, default)
        
        try:
            json_data = {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
            }
            if language:
                json_data["language"] = language
            
            response = await self.client.post(
                f"{self.base_url}/api/v1/users/",
                json=json_data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting/creating user: {e}")
            return None
    
    async def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user by telegram ID."""
        return await self._handle_request(
            f"getting user {telegram_id}",
            lambda: self.client.get(f"{self.base_url}/api/v1/users/{telegram_id}"),
            None
        )
    
    async def update_user(
        self,
        telegram_id: int,
        status: Optional[str] = None,
        user_role: Optional[str] = None,
        bonus_channels_count: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update user fields."""
        data = {}
        if status:
            data["status"] = status
        if user_role:
            data["user_role"] = user_role
        if bonus_channels_count is not None:
            data["bonus_channels_count"] = bonus_channels_count
        
        return await self._handle_request(
            f"updating user {telegram_id}",
            lambda: self.client.patch(
                f"{self.base_url}/api/v1/users/{telegram_id}",
                json=data
            ),
            None
        )
    
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
    
    async def get_user_language(self, telegram_id: int) -> str:
        """Get user's preferred language. Defaults to 'en_US'."""
        result = await self._handle_request(
            f"getting user language {telegram_id}",
            lambda: self.client.get(f"{self.base_url}/api/v1/users/{telegram_id}/language"),
            {"language": "en_US"},
            log_error=False  # Don't log 404 as error, it's expected for new users
        )
        return result.get("language", "en_US") if isinstance(result, dict) else "en_US"
    
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
        return await self._handle_request(
            "getting feed users",
            lambda: self.client.get(f"{self.base_url}/api/v1/users/feed-targets"),
            []
        )
    
    async def delete_user(self, telegram_id: int, hard: bool = False) -> bool:
        """Delete a user (soft or hard delete)."""
        try:
            response = await self.client.delete(
                f"{self.base_url}/api/v1/users/{telegram_id}",
                params={"hard": hard}
            )
            return response.status_code == 204
        except Exception as e:
            logger.error(f"Error deleting user {telegram_id}: {e}")
            return False

    async def get_feed_eligible(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Check if user is eligible for feed and mailing (has taste cluster, TRAINED/ACTIVE)."""
        return await self._handle_request(
            f"getting feed eligible for {telegram_id}",
            lambda: self.client.get(f"{self.base_url}/api/v1/users/{telegram_id}/feed-eligible"),
            None,
        )

    async def mark_training_complete(
        self, telegram_id: int, *, skip_notify: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Mark user training as complete. skip_notify=True when completion was from chat (no Redis)."""
        url = f"{self.base_url}/api/v1/users/{telegram_id}/training-complete"
        if skip_notify:
            url += "?skip_notify=true"
        return await self._handle_request(
            f"marking training complete for {telegram_id}",
            lambda: self.client.post(url),
            None,
        )

