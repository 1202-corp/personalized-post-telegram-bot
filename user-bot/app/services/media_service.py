"""
Service for downloading media files from Telegram channels.
"""
import logging
import io
from typing import Optional

from PIL import Image

from app.types import MediaServiceProtocol, TelethonServiceProtocol

logger = logging.getLogger(__name__)

# Quality settings for image compression
PHOTO_MAX_SIZE = 800  # Max width/height in pixels
PHOTO_QUALITY = 50  # JPEG quality (0-100, lower = smaller file)


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
            
            # Compress photo for faster loading
            return self._compress_image(data)
        except Exception as e:
            logger.error(f"Error downloading photo from @{username} (msg {message_id}): {e}")
            return None
    
    def _compress_image(self, data: bytes) -> bytes:
        """
        Compress image to lower quality for faster loading.
        
        Args:
            data: Original image bytes
            
        Returns:
            Compressed image bytes
        """
        try:
            img = Image.open(io.BytesIO(data))
            
            # Convert to RGB if necessary (for PNG with alpha)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Resize if too large
            if img.width > PHOTO_MAX_SIZE or img.height > PHOTO_MAX_SIZE:
                img.thumbnail((PHOTO_MAX_SIZE, PHOTO_MAX_SIZE), Image.Resampling.LANCZOS)
            
            # Compress to JPEG
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=PHOTO_QUALITY, optimize=True)
            return output.getvalue()
        except Exception as e:
            logger.warning(f"Failed to compress image: {e}, returning original")
            return data
    
    async def download_video(self, username: str, message_id: int) -> Optional[bytes]:
        """
        Download video thumbnail (first frame) for a specific channel message.
        
        Returns the video thumbnail as a compressed image instead of the full video
        for faster loading in the miniapp.
        
        Args:
            username: Channel username (with or without @)
            message_id: Telegram message ID
            
        Returns:
            Thumbnail image bytes or None if not found/failed
        """
        await self.telethon_service.ensure_connected()
        
        username = username.lstrip("@").lower()
        
        try:
            entity = await self.telethon_service._get_entity(username)
            message = await self.telethon_service._get_message(entity, message_id)
            
            if not message or not message.video:
                return None
            
            # Download video thumbnail instead of full video
            # Telethon can download just the thumbnail
            if message.video.thumbs:
                # Download the thumbnail directly
                data: bytes = await self.telethon_service._download_media(
                    message, bytes, thumb=-1  # -1 = largest thumbnail
                )
                if data:
                    return self._compress_image(data)
            
            # Fallback: if no thumbnail, return None (don't download full video)
            logger.warning(f"No thumbnail available for video @{username} (msg {message_id})")
            return None
        except Exception as e:
            logger.error(f"Error downloading video thumbnail from @{username} (msg {message_id}): {e}")
            return None

