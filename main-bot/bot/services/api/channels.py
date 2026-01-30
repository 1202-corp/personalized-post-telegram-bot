"""Channel service for API interactions."""

import logging
from typing import List, Dict, Any, Optional
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

    async def get_channels_need_refresh(self, channel_usernames: List[str]) -> List[str]:
        """Return channel usernames that need scraping (not in DB or metadata older than TTL)."""
        if not channel_usernames:
            return []
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/channels/need-refresh",
                json={"channel_usernames": channel_usernames},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("channel_usernames", [])
        except Exception as e:
            logger.warning(f"Error checking channels need-refresh: {e}, will scrape all")
            return list(channel_usernames)  # on error, refresh all to be safe
    
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
    
    async def get_users_by_channel(self, channel_username: str) -> List[Dict[str, Any]]:
        """Get all users subscribed to a channel."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/channels/{channel_username}/users"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting users for channel {channel_username}: {e}")
            return []

    async def get_mailing_recipients_by_telegram_id(
        self, channel_telegram_id: int
    ) -> List[int]:
        """Get telegram_ids of users who receive mailing for this channel (by Telegram channel id)."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/channels/by-telegram-id/{channel_telegram_id}/mailing-recipients"
            )
            response.raise_for_status()
            data = response.json()
            return data.get("telegram_ids", [])
        except Exception as e:
            logger.error(f"Error getting mailing recipients for channel {channel_telegram_id}: {e}")
            return []

    async def get_user_channels_with_meta(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Get user's channels with mailing_enabled and stats."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/channels/user/{telegram_id}/channels/with-meta"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting user channels with meta: {e}")
            return []

    async def get_user_channel_detail(
        self, telegram_id: int, channel_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get channel detail for user (stats, mailing_enabled)."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/channels/user/{telegram_id}/channels/{channel_id}/detail"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting channel detail: {e}")
            return None

    async def patch_user_channel_mailing(
        self, telegram_id: int, channel_id: int, mailing_enabled: bool
    ) -> Optional[Dict[str, Any]]:
        """Set mailing_enabled for user's channel."""
        try:
            response = await self.client.patch(
                f"{self.base_url}/api/v1/channels/user/{telegram_id}/channels/{channel_id}",
                json={"mailing_enabled": mailing_enabled},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error toggling mailing: {e}")
            return None

    async def patch_user_all_channels_mailing(
        self, telegram_id: int, mailing_enabled: bool
    ) -> Optional[Dict[str, Any]]:
        """Set mailing_enabled for all user's channels at once."""
        try:
            response = await self.client.patch(
                f"{self.base_url}/api/v1/channels/user/{telegram_id}/channels/mailing-all",
                json={"mailing_enabled": mailing_enabled},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error toggling all channels mailing: {e}")
            return None

    async def delete_user_channel(self, telegram_id: int, channel_id: int) -> bool:
        """Remove channel from user's subscriptions."""
        try:
            response = await self.client.delete(
                f"{self.base_url}/api/v1/channels/user/{telegram_id}/channels/{channel_id}"
            )
            return response.status_code == 204
        except Exception as e:
            logger.error(f"Error deleting user channel: {e}")
            return False

    async def get_channel_avatar_bytes(self, channel_id: int) -> Optional[bytes]:
        """Get channel avatar image bytes. Returns None if no avatar or on error."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/channels/{channel_id}/avatar"
            )
            if response.status_code != 200:
                return None
            return response.content
        except Exception as e:
            logger.error(f"Error getting channel avatar: {e}")
            return None

