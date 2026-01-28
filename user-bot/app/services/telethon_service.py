"""
Telethon service for Telegram channel operations.
"""
import asyncio
import logging
from typing import Optional, List, Dict
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest
from telethon.tl.types import Channel, Message
from telethon.errors import (
    ChannelPrivateError,
    ChannelInvalidError,
    UsernameNotOccupiedError,
    FloodWaitError,
)

from app.core.config import get_settings
from app.core.utils import get_message_html
from app.types import ChannelInfo, ScrapeResult, PostDataDict, TelethonServiceProtocol

logger = logging.getLogger(__name__)
settings = get_settings()


class TelethonService:
    """
    Service for Telegram channel operations using Telethon.
    
    Handles connection management and provides async methods for scraping and joining channels.
    """
    
    def __init__(self):
        """Initialize Telethon service."""
        self._client: Optional[TelegramClient] = None
        self._connected = False
        self._lock = asyncio.Lock()
    
    async def connect(self) -> None:
        """Connect to Telegram."""
        async with self._lock:
            if self._connected:
                return
            
            try:
                session = StringSession(settings.telegram_session_string)
                self._client = TelegramClient(
                    session,
                    settings.telegram_api_id,
                    settings.telegram_api_hash,
                )
                await self._client.connect()
                
                if not await self._client.is_user_authorized():
                    logger.error("Telegram client not authorized. Please generate a session string.")
                    raise RuntimeError("Telegram client not authorized")
                
                self._connected = True
                logger.info("Telethon client connected successfully")
            except Exception as e:
                logger.error(f"Failed to connect Telethon client: {e}")
                raise
    
    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        async with self._lock:
            if self._client:
                await self._client.disconnect()
                self._connected = False
                logger.info("Telethon client disconnected")
    
    async def ensure_connected(self) -> None:
        """Ensure client is connected."""
        if not self._connected:
            await self.connect()
    
    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected
    
    @property
    def client(self) -> Optional[TelegramClient]:
        """Get Telethon client instance (for event handlers)."""
        return self._client
    
    async def join_channel(self, username: str) -> ChannelInfo:
        """
        Join a channel by username.
        
        Args:
            username: Channel username (with or without @)
            
        Returns:
            ChannelInfo dictionary with result
        """
        await self.ensure_connected()
        
        # Normalize username
        username = username.lstrip("@")
        
        try:
            # Get channel entity
            entity = await self._client.get_entity(username)
            
            if not isinstance(entity, Channel):
                return {
                    "success": False,
                    "channel_username": username,
                    "channel_id": None,
                    "channel_title": None,
                    "message": "Entity is not a channel"
                }
            
            # Check if already a member
            await self._client(GetFullChannelRequest(entity))
            
            # Try to join if not a member
            try:
                await self._client(JoinChannelRequest(entity))
                logger.info(f"Joined channel @{username}")
            except Exception as e:
                # Might already be a member
                logger.debug(f"Join channel result: {e}")
            
            return {
                "success": True,
                "channel_username": username,
                "channel_id": entity.id,
                "channel_title": entity.title,
                "message": "Channel joined successfully"
            }
        
        except ChannelPrivateError:
            return {
                "success": False,
                "channel_username": username,
                "channel_id": None,
                "channel_title": None,
                "message": "Channel is private"
            }
        except ChannelInvalidError:
            return {
                "success": False,
                "channel_username": username,
                "channel_id": None,
                "channel_title": None,
                "message": "Invalid channel"
            }
        except UsernameNotOccupiedError:
            return {
                "success": False,
                "channel_username": username,
                "channel_id": None,
                "channel_title": None,
                "message": "Channel not found"
            }
        except FloodWaitError as e:
            return {
                "success": False,
                "channel_username": username,
                "channel_id": None,
                "channel_title": None,
                "message": f"Rate limited. Wait {e.seconds} seconds"
            }
        except Exception as e:
            logger.error(f"Error joining channel @{username}: {e}")
            return {
                "success": False,
                "channel_username": username,
                "channel_id": None,
                "channel_title": None,
                "message": str(e)
            }
    
    async def scrape_channel(
        self,
        username: str,
        limit: int = 7
    ) -> ScrapeResult:
        """
        Scrape recent messages from a channel.
        
        Args:
            username: Channel username (with or without @)
            limit: Maximum number of posts to return
            
        Returns:
            ScrapeResult dictionary with posts
        """
        await self.ensure_connected()
        
        username = username.lstrip("@")
        
        try:
            # Get channel entity
            entity = await self._get_channel_entity(username)
            if not entity:
                return self._create_error_result(username, "Entity is not a channel")
            
            # Fetch messages
            messages: List[Message] = await self._client.get_messages(
                entity,
                limit=limit * 3
            )
            
            # Process messages
            posts = await self._process_messages(messages, entity, username)
            
            logger.info(f"Scraped {len(posts)} posts from @{username}")
            
            return {
                "success": True,
                "channel_username": username,
                "channel_telegram_id": entity.id,
                "channel_title": entity.title,
                "posts": posts,
                "posts_count": len(posts),
                "message": f"Scraped {len(posts)} posts"
            }
        
        except ChannelPrivateError:
            return self._create_error_result(username, "Channel is private")
        except UsernameNotOccupiedError:
            return self._create_error_result(username, "Channel not found")
        except FloodWaitError as e:
            return self._create_error_result(username, f"Rate limited. Wait {e.seconds} seconds")
        except Exception as e:
            logger.error(f"Error scraping channel @{username}: {e}")
            return self._create_error_result(username, str(e))
    
    async def _get_channel_entity(self, username: str) -> Optional[Channel]:
        """Get channel entity by username."""
        try:
            entity = await self._client.get_entity(username)
            if isinstance(entity, Channel):
                return entity
            return None
        except Exception:
            return None
    
    async def _process_messages(
        self,
        messages: List[Message],
        entity: Channel,
        username: str
    ) -> List[PostDataDict]:
        """
        Process messages and convert to post data.
        
        Args:
            messages: List of Telethon Message objects
            entity: Channel entity
            username: Channel username
            
        Returns:
            List of post data dictionaries
        """
        # Group media albums (messages with the same grouped_id)
        albums: Dict[int, List[Message]] = {}
        singles: List[Message] = []
        
        for msg in messages:
            if msg.grouped_id:
                albums.setdefault(msg.grouped_id, []).append(msg)
            else:
                singles.append(msg)
        
        posts: List[PostDataDict] = []
        
        # Process single messages
        posts.extend(await self._process_single_messages(singles, entity, username))
        
        # Process albums
        posts.extend(await self._process_albums(albums, entity, username))
        
        return posts
    
    async def _process_single_messages(
        self,
        messages: List[Message],
        entity: Channel,
        username: str
    ) -> List[PostDataDict]:
        """Process single (non-album) messages."""
        posts: List[PostDataDict] = []
        
        for msg in messages:
            raw_text = (msg.message or "").strip()
            if not raw_text:
                continue  # skip pure-media posts without caption
            
            # Get message text
            text = get_message_html(msg)
            
            posts.append({
                "telegram_message_id": msg.id,
                "text": text,
                "media_type": self.get_media_type(msg),
                "media_file_id": str(msg.id),
                "posted_at": msg.date.isoformat() if msg.date else datetime.utcnow().isoformat(),
                "channel_telegram_id": entity.id,
                "channel_username": username,
                "channel_title": entity.title,
            })
        
        return posts
    
    async def _process_albums(
        self,
        albums: Dict[int, List[Message]],
        entity: Channel,
        username: str
    ) -> List[PostDataDict]:
        """Process album (grouped) messages."""
        posts: List[PostDataDict] = []
        
        for grouped_id, group_messages in albums.items():
            # Prefer message with non-empty text; if none, skip whole album
            sorted_group = sorted(group_messages, key=lambda m: m.date or datetime.utcnow())
            main: Optional[Message] = None
            for m in sorted_group:
                if (m.message or "").strip():
                    main = m
                    break
            if main is None:
                # Album has no caption text, skip
                continue
            
            # Get message text
            text = get_message_html(main)
            # Collect all message IDs in the album for later media group sending
            all_ids = sorted({m.id for m in group_messages})
            media_file_id = ",".join(str(mid) for mid in all_ids)
            
            posts.append({
                "telegram_message_id": main.id,
                "text": text,
                "media_type": self.get_media_type(main),
                "media_file_id": media_file_id,
                "posted_at": main.date.isoformat() if main.date else datetime.utcnow().isoformat(),
                "channel_telegram_id": entity.id,
                "channel_username": username,
                "channel_title": entity.title,
            })
        
        return posts
    
    def get_media_type(self, message: Message) -> Optional[str]:
        """
        Get media type from message.
        
        Args:
            message: Telethon Message object
            
        Returns:
            Media type string or None
        """
        if not message.media:
            return None
        
        media_type = type(message.media).__name__
        
        if "Photo" in media_type:
            return "photo"
        elif "Document" in media_type:
            if message.video:
                return "video"
            elif message.audio:
                return "audio"
            elif message.voice:
                return "voice"
            return "document"
        elif "Video" in media_type:
            return "video"
        
        return "other"
    
    def _create_error_result(self, username: str, message: str) -> ScrapeResult:
        """Create error result dictionary."""
        return {
            "success": False,
            "channel_username": username,
            "channel_telegram_id": None,
            "channel_title": None,
            "posts": [],
            "posts_count": 0,
            "message": message
        }
    
    # Helper methods for MediaService
    async def _get_entity(self, username: str):
        """Get entity by username (for MediaService)."""
        await self.ensure_connected()
        return await self._client.get_entity(username)
    
    async def _get_message(self, entity, message_id: int) -> Optional[Message]:
        """Get message by ID (for MediaService)."""
        await self.ensure_connected()
        return await self._client.get_messages(entity, ids=message_id)
    
    async def _download_media(self, message: Message, file: type = bytes, thumb: int = None) -> bytes:
        """Download media from message (for MediaService).
        
        Args:
            message: Message with media
            file: Output type (bytes)
            thumb: Thumbnail index (-1 for largest, None for full media)
        """
        await self.ensure_connected()
        if thumb is not None:
            return await self._client.download_media(message, file, thumb=thumb)
        return await self._client.download_media(message, file)
    
    async def start_listening(self) -> None:
        """Start listening for new messages (run event loop)."""
        await self.ensure_connected()
        logger.info("Starting Telethon event loop for real-time posts...")
        await self._client.run_until_disconnected()


# Singleton instance
_telethon_service: Optional[TelethonService] = None


def get_telethon_service() -> TelethonService:
    """Get singleton TelethonService instance."""
    global _telethon_service
    if _telethon_service is None:
        _telethon_service = TelethonService()
    return _telethon_service

