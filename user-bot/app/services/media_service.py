"""
Service for downloading media files from Telegram channels.
"""
import logging
from typing import Optional

from app.types import MediaServiceProtocol, TelethonServiceProtocol

logger = logging.getLogger(__name__)


class MediaService:
    """Service for downloading media files."""
    
    def __init__(self, telethon_service: TelethonServiceProtocol):
        """
        Initialize media service.
        
        Args:
            telethon_service: Telethon service instance
        """
        self.telethon_service = telethon_service
    
    async def download_photo(self, username: str, message_id: int) -> Optional[bytes]:
        """
        Download photo bytes for a specific channel message.
        
        Used by main-bot via user-bot HTTP API to resend photos to the user.
        
        Args:
            username: Channel username (with or without @)
            message_id: Telegram message ID
            
        Returns:
            Photo bytes or None if not found/failed
        """
        await self.telethon_service.ensure_connected()
        
        username = username.lstrip("@").lower()
        
        try:
            entity = await self.telethon_service._get_entity(username)
            message = await self.telethon_service._get_message(entity, message_id)
            
            if not message or not message.photo:
                return None
            
            # Telethon can download media into memory as bytes
            data: bytes = await self.telethon_service._download_media(message, bytes)
            return data
        except Exception as e:
            logger.error(f"Error downloading photo from @{username} (msg {message_id}): {e}")
            return None
    
    async def download_video(self, username: str, message_id: int) -> Optional[bytes]:
        """
        Download video bytes for a specific channel message.
        
        Used by main-bot via user-bot HTTP API to resend videos to the user.
        
        Args:
            username: Channel username (with or without @)
            message_id: Telegram message ID
            
        Returns:
            Video bytes or None if not found/failed
        """
        await self.telethon_service.ensure_connected()
        
        username = username.lstrip("@").lower()
        
        try:
            entity = await self.telethon_service._get_entity(username)
            message = await self.telethon_service._get_message(entity, message_id)
            
            if not message or not message.video:
                return None
            
            # Telethon can download media into memory as bytes
            data: bytes = await self.telethon_service._download_media(message, bytes)
            return data
        except Exception as e:
            logger.error(f"Error downloading video from @{username} (msg {message_id}): {e}")
            return None

