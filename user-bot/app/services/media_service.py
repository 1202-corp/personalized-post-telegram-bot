"""
Service for downloading media files from Telegram channels.
"""
import logging
import io
from typing import Optional

from PIL import Image

from app.core.utils import get_message_html
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
    
    def _draw_play_overlay(self, image_bytes: bytes) -> bytes:
        """
        Draw a play button (triangle) in the center with gray semi-transparent background.
        Main-bot never receives video; user-bot sends video as this photo.
        
        Args:
            image_bytes: Original image bytes (e.g. video thumbnail)
            
        Returns:
            JPEG bytes with play overlay
        """
        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            w, h = img.size
            # Gray semi-transparent overlay in center (circle or rounded rect)
            overlay_size = min(w, h) // 4
            cx, cy = w // 2, h // 2
            from PIL import ImageDraw
            draw = ImageDraw.Draw(img, 'RGBA')
            # Circle background for play button (gray, semi-transparent)
            r = overlay_size // 2
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(128, 128, 128, 180))
            # Play triangle (white, pointing right)
            tri_size = r // 2
            points = [
                (cx - tri_size, cy - tri_size),
                (cx - tri_size, cy + tri_size),
                (cx + tri_size, cy),
            ]
            draw.polygon(points, fill=(255, 255, 255, 255))
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=PHOTO_QUALITY, optimize=True)
            return output.getvalue()
        except Exception as e:
            logger.warning(f"Failed to draw play overlay: {e}, returning original")
            return image_bytes
    
    async def download_video(self, username: str, message_id: int) -> Optional[bytes]:
        """
        Get video as photo: first frame (thumbnail) + play button in center.
        Main-bot never receives video; this returns JPEG for display.
        
        Args:
            username: Channel username (with or without @)
            message_id: Telegram message ID
            
        Returns:
            JPEG bytes (thumbnail with play overlay) or None if not found/failed
        """
        await self.telethon_service.ensure_connected()
        
        username = username.lstrip("@").lower()
        
        try:
            entity = await self.telethon_service._get_entity(username)
            message = await self.telethon_service._get_message(entity, message_id)
            
            if not message or not message.video:
                return None
            
            if not message.video.thumbs:
                logger.warning(f"No thumbnail for video @{username} (msg {message_id})")
                return None
            
            data: bytes = await self.telethon_service._download_media(
                message, bytes, thumb=-1
            )
            if not data:
                return None
            compressed = self._compress_image(data)
            return self._draw_play_overlay(compressed)
        except Exception as e:
            logger.error(f"Error getting video as photo from @{username} (msg {message_id}): {e}")
            return None
    
    async def get_post_text(self, username: str, message_id: int) -> Optional[str]:
        """
        Get post text in HTML format for a specific channel message.
        
        Used by main-bot via user-bot HTTP API to get post text during training.
        
        Args:
            username: Channel username (with or without @)
            message_id: Telegram message ID
            
        Returns:
            HTML formatted text or None if not found/failed
        """
        await self.telethon_service.ensure_connected()
        
        username = username.lstrip("@").lower()
        
        try:
            entity = await self.telethon_service._get_entity(username)
            message = await self.telethon_service._get_message(entity, message_id)
            
            if not message:
                return None
            
            # Get HTML formatted text
            text = get_message_html(message)
            return text if text else None
        except Exception as e:
            logger.error(f"Error getting post text from @{username} (msg {message_id}): {e}")
            return None
    
    async def get_post_full_content(
        self,
        username: str,
        message_id: int
    ) -> Optional[dict]:
        """
        Get full post content (text and media) for a specific channel message.
        
        Used by main-bot via user-bot HTTP API to get post content for caching.
        
        Args:
            username: Channel username (with or without @)
            message_id: Telegram message ID
            
        Returns:
            Dict with keys: text, media_type, media_data (base64 encoded bytes)
            or None if not found/failed
        """
        await self.telethon_service.ensure_connected()
        
        username = username.lstrip("@").lower()
        
        try:
            import base64
            
            entity = await self.telethon_service._get_entity(username)
            message = await self.telethon_service._get_message(entity, message_id)
            
            if not message:
                return None
            
            result = {}
            
            # Get text
            text = get_message_html(message)
            if text:
                result["text"] = text
            
            # Get media
            media_type = None
            media_data = None
            
            if message.photo:
                media_type = "photo"
                photo_bytes = await self.download_photo(username, message_id)
                if photo_bytes:
                    media_data = base64.b64encode(photo_bytes).decode('utf-8')
            elif message.video:
                # Return video as photo (first frame + play overlay); main-bot never receives video
                media_type = "photo"
                video_as_photo = await self.download_video(username, message_id)
                if video_as_photo:
                    media_data = base64.b64encode(video_as_photo).decode('utf-8')
            
            if media_type:
                result["media_type"] = media_type
            if media_data:
                result["media_data"] = media_data
            
            return result if result else None
        except Exception as e:
            logger.error(f"Error getting full post content from @{username} (msg {message_id}): {e}")
            return None

