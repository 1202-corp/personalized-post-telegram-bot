"""Channel service for API interactions."""

import logging
from typing import List, Dict, Any
from .base import BaseAPIClient

logger = logging.getLogger(__name__)


class ChannelService(BaseAPIClient):
    """Service for channel-related API endpoints."""
    
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

