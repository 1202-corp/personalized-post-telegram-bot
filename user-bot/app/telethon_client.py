"""
Telethon client wrapper for scraping Telegram channels.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest
from telethon.tl.types import Channel, Message
from telethon.errors import (
    ChannelPrivateError,
    ChannelInvalidError,
    UsernameNotOccupiedError,
    FloodWaitError,
)
import json
import redis.asyncio as aioredis
import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def get_message_markdown(message) -> str:
    """Get message text with MarkdownV2 formatting.
    
    Converts Telegram entities to MarkdownV2 format with proper escaping.
    """
    text = message.raw_text or message.message or ""
    entities = message.entities
    
    if not entities or not text:
        return escape_markdown_v2(text)
    
    # Sort entities by offset
    sorted_entities = sorted(entities, key=lambda e: e.offset)
    
    # Build result piece by piece
    result = []
    last_end = 0
    
    for entity in sorted_entities:
        start = entity.offset
        end = entity.offset + entity.length
        entity_type = type(entity).__name__
        
        # Add escaped text before this entity
        if start > last_end:
            result.append(escape_markdown_v2(text[last_end:start]))
        
        # Get entity content (escaped)
        content = text[start:end]
        escaped_content = escape_markdown_v2(content)
        
        # Apply formatting based on entity type
        if entity_type == "MessageEntityBold":
            result.append(f"*{escaped_content}*")
        elif entity_type == "MessageEntityItalic":
            result.append(f"_{escaped_content}_")
        elif entity_type == "MessageEntityCode":
            # Code doesn't need escaping inside
            result.append(f"`{content}`")
        elif entity_type == "MessageEntityPre":
            result.append(f"```\n{content}\n```")
        elif entity_type == "MessageEntityStrike":
            result.append(f"~{escaped_content}~")
        elif entity_type == "MessageEntityUnderline":
            result.append(f"__{escaped_content}__")
        elif entity_type == "MessageEntityTextUrl":
            # URL needs escaping for special chars
            escaped_url = entity.url.replace(')', '\\)').replace('(', '\\(')
            result.append(f"[{escaped_content}]({escaped_url})")
        elif entity_type == "MessageEntityBlockquote":
            # Blockquote: escape content and add > to each line
            lines = escaped_content.split('\n')
            quoted = '\n'.join(f">{line}" for line in lines)
            result.append(quoted)
        elif entity_type == "MessageEntitySpoiler":
            result.append(f"||{escaped_content}||")
        else:
            # Unknown entity - just add escaped content
            result.append(escaped_content)
        
        last_end = end
    
    # Add remaining text after last entity
    if last_end < len(text):
        result.append(escape_markdown_v2(text[last_end:]))
    
    return ''.join(result)


class TelethonClientWrapper:
    """
    Wrapper around Telethon client for channel operations.
    Handles connection management and provides async methods for scraping.
    """
    
    def __init__(self):
        self._client: Optional[TelegramClient] = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._event_handler_registered = False
    
    async def connect(self):
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
                
                # Register event handler for real-time post detection
                await self._register_event_handler()
            except Exception as e:
                logger.error(f"Failed to connect Telethon client: {e}")
                raise
    
    async def disconnect(self):
        """Disconnect from Telegram."""
        async with self._lock:
            if self._client:
                await self._client.disconnect()
                self._connected = False
                logger.info("Telethon client disconnected")
    
    async def ensure_connected(self):
        """Ensure client is connected."""
        if not self._connected:
            await self.connect()
    
    async def join_channel(self, username: str) -> Dict[str, Any]:
        """
        Join a channel by username.
        Returns channel info if successful.
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
                    "message": "Entity is not a channel"
                }
            
            # Check if already a member
            full_channel = await self._client(GetFullChannelRequest(entity))
            
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
                "message": "Channel is private"
            }
        except ChannelInvalidError:
            return {
                "success": False,
                "channel_username": username,
                "channel_id": None,
                "message": "Invalid channel"
            }
        except UsernameNotOccupiedError:
            return {
                "success": False,
                "channel_username": username,
                "channel_id": None,
                "message": "Channel not found"
            }
        except FloodWaitError as e:
            return {
                "success": False,
                "channel_username": username,
                "channel_id": None,
                "message": f"Rate limited. Wait {e.seconds} seconds"
            }
        except Exception as e:
            logger.error(f"Error joining channel @{username}: {e}")
            return {
                "success": False,
                "channel_username": username,
                "channel_id": None,
                "message": str(e)
            }
    
    async def scrape_channel(
        self,
        username: str,
        limit: int = 7
    ) -> Dict[str, Any]:
        """
        Scrape recent messages from a channel.
        Returns list of messages.
        """
        await self.ensure_connected()
        
        username = username.lstrip("@")
        
        try:
            # Get channel entity
            entity = await self._client.get_entity(username)
            
            if not isinstance(entity, Channel):
                return {
                    "success": False,
                    "channel_username": username,
                    "posts": [],
                    "posts_count": 0,
                    "message": "Entity is not a channel"
                }
            
            # Fetch more messages than needed to account for filtering
            messages: List[Message] = await self._client.get_messages(
                entity,
                limit=limit * 3
            )

            # Group media albums (messages with the same grouped_id)
            albums: Dict[int, List[Message]] = {}
            singles: List[Message] = []

            for msg in messages:
                if msg.grouped_id:
                    albums.setdefault(msg.grouped_id, []).append(msg)
                else:
                    singles.append(msg)

            posts: List[Dict[str, Any]] = []

            # Process single messages: keep only posts with non-empty text
            for msg in singles:
                raw_text = (msg.message or "").strip()
                if not raw_text:
                    continue  # skip pure-media posts without caption
                
                # Get message text
                text = get_message_markdown(msg)

                posts.append({
                    "telegram_message_id": msg.id,
                    "text": text,
                    "media_type": self._get_media_type(msg),
                    "media_file_id": str(msg.id),
                    "posted_at": msg.date.isoformat() if msg.date else datetime.utcnow().isoformat(),
                    "channel_telegram_id": entity.id,
                    "channel_username": username,
                    "channel_title": entity.title,
                })

            # Process albums: treat each grouped_id as a single logical post
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
                text = get_message_markdown(main)
                # Collect all message IDs in the album for later media group sending
                all_ids = sorted({m.id for m in group_messages})
                media_file_id = ",".join(str(mid) for mid in all_ids)

                posts.append({
                    "telegram_message_id": main.id,
                    "text": text,
                    "media_type": self._get_media_type(main),
                    "media_file_id": media_file_id,
                    "posted_at": main.date.isoformat() if main.date else datetime.utcnow().isoformat(),
                    "channel_telegram_id": entity.id,
                    "channel_username": username,
                    "channel_title": entity.title,
                })
            
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
            return {
                "success": False,
                "channel_username": username,
                "posts": [],
                "posts_count": 0,
                "message": "Channel is private"
            }
        except UsernameNotOccupiedError:
            return {
                "success": False,
                "channel_username": username,
                "posts": [],
                "posts_count": 0,
                "message": "Channel not found"
            }
        except FloodWaitError as e:
            return {
                "success": False,
                "channel_username": username,
                "posts": [],
                "posts_count": 0,
                "message": f"Rate limited. Wait {e.seconds} seconds"
            }
        except Exception as e:
            logger.error(f"Error scraping channel @{username}: {e}")
            return {
                "success": False,
                "channel_username": username,
                "posts": [],
                "posts_count": 0,
                "message": str(e)
            }
    
    async def download_photo(self, username: str, message_id: int) -> Optional[bytes]:
        """Download photo bytes for a specific channel message.

        Used by main-bot via user-bot HTTP API to resend photos to the user.
        """
        await self.ensure_connected()

        username = username.lstrip("@").lower()

        try:
            entity = await self._client.get_entity(username)
            message: Message = await self._client.get_messages(entity, ids=message_id)
            if not message or not message.photo:
                return None

            # Telethon can download media into memory as bytes
            data: bytes = await self._client.download_media(message, bytes)
            return data
        except Exception as e:
            logger.error(f"Error downloading photo from @{username} (msg {message_id}): {e}")
            return None

    async def download_video(self, username: str, message_id: int) -> Optional[bytes]:
        """Download video bytes for a specific channel message.

        Used by main-bot via user-bot HTTP API to resend videos to the user.
        """
        await self.ensure_connected()

        username = username.lstrip("@").lower()

        try:
            entity = await self._client.get_entity(username)
            message: Message = await self._client.get_messages(entity, ids=message_id)
            if not message or not message.video:
                return None

            # Telethon can download media into memory as bytes
            data: bytes = await self._client.download_media(message, bytes)
            return data
        except Exception as e:
            logger.error(f"Error downloading video from @{username} (msg {message_id}): {e}")
            return None
    
    def _get_media_type(self, message: Message) -> Optional[str]:
        """Get media type from message."""
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
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    async def _register_event_handler(self):
        """Register event handler for new messages in channels."""
        if self._event_handler_registered:
            return
        
        # Track pending album messages for grouping
        pending_albums: dict[int, list] = {}
        album_timers: dict[int, asyncio.Task] = {}
        
        async def process_album(grouped_id: int, channel_id: int, channel_username: str, channel_title: str):
            """Process collected album messages."""
            await asyncio.sleep(1.5)  # Wait for all album messages to arrive
            
            if grouped_id not in pending_albums:
                return
            
            messages = pending_albums.pop(grouped_id, [])
            album_timers.pop(grouped_id, None)
            
            if not messages:
                return
            
            # Sort by message id
            messages.sort(key=lambda m: m.id)
            
            # Find message with text (caption)
            main_msg = None
            for m in messages:
                if (m.message or "").strip():
                    main_msg = m
                    break
            
            if main_msg is None:
                main_msg = messages[0]
            
            # Get message text
            text = get_message_markdown(main_msg)
            all_ids = [m.id for m in messages]
            media_file_id = ",".join(str(mid) for mid in all_ids)
            
            post_data = {
                "telegram_message_id": main_msg.id,
                "text": text,
                "media_type": self._get_media_type(main_msg),
                "media_file_id": media_file_id,
                "posted_at": main_msg.date.isoformat() if main_msg.date else datetime.utcnow().isoformat(),
            }
            
            logger.info(f"Real-time: Album with {len(messages)} photos in @{channel_username}")
            
            post_id = await self._sync_realtime_post(channel_id, channel_username, channel_title, post_data)
            await self._notify_realtime_post(channel_id, channel_username, channel_title, post_data, post_id)
        
        @self._client.on(events.NewMessage(chats=None))
        async def handle_new_message(event):
            """Handle new messages from channels in real-time."""
            try:
                # Only process channel posts
                if not event.is_channel:
                    return
                
                message = event.message
                
                # Skip old messages (only process messages from last 60 seconds)
                if message.date:
                    message_age = (datetime.utcnow() - message.date.replace(tzinfo=None)).total_seconds()
                    if message_age > 60:
                        return
                
                chat = await event.get_chat()
                
                # Skip messages without text and without media
                if not message.text and not message.media:
                    return
                
                # Get channel info
                channel_username = getattr(chat, 'username', None) or str(chat.id)
                channel_title = getattr(chat, 'title', 'Unknown')
                channel_id = chat.id
                
                # Handle album (grouped messages)
                if message.grouped_id:
                    grouped_id = message.grouped_id
                    if grouped_id not in pending_albums:
                        pending_albums[grouped_id] = []
                    pending_albums[grouped_id].append(message)
                    
                    # Start/restart timer for this album
                    if grouped_id in album_timers:
                        album_timers[grouped_id].cancel()
                    album_timers[grouped_id] = asyncio.create_task(
                        process_album(grouped_id, channel_id, channel_username, channel_title)
                    )
                    return
                
                logger.info(f"Real-time: New post in @{channel_username}")
                
                # Prepare post data for single message
                text = get_message_markdown(message)
                post_data = {
                    "telegram_message_id": message.id,
                    "text": text,
                    "media_type": self._get_media_type(message),
                    "media_file_id": str(message.id) if message.media else None,
                    "posted_at": message.date.isoformat() if message.date else datetime.utcnow().isoformat(),
                }
                
                # Sync to core-api and get post_id
                post_id = await self._sync_realtime_post(channel_id, channel_username, channel_title, post_data)
                
                # Notify main-bot via Redis for instant delivery
                await self._notify_realtime_post(channel_id, channel_username, channel_title, post_data, post_id)
                
            except Exception as e:
                logger.error(f"Error handling real-time message: {e}")
        
        self._event_handler_registered = True
        logger.info("Real-time event handler registered for channel posts")
    
    async def _sync_realtime_post(self, channel_id: int, channel_username: str, channel_title: str, post_data: dict) -> int | None:
        """Sync a single post to core-api. Returns the created post_id."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Ensure channel exists
                await client.post(
                    f"{settings.core_api_url}/api/v1/channels/",
                    json={
                        "telegram_id": channel_id,
                        "username": channel_username,
                        "title": channel_title,
                        "is_default": False,
                    }
                )
                
                # Create post
                response = await client.post(
                    f"{settings.core_api_url}/api/v1/posts/bulk",
                    json={
                        "channel_telegram_id": channel_id,
                        "posts": [post_data],
                    }
                )
                
                # Try to get post_id from response
                if response.status_code == 201:
                    data = response.json()
                    if data and "post_ids" in data and len(data["post_ids"]) > 0:
                        return data["post_ids"][0]
                return None
        except Exception as e:
            logger.error(f"Failed to sync real-time post: {e}")
            return None
    
    async def _notify_realtime_post(self, channel_id: int, channel_username: str, channel_title: str, post_data: dict, post_id: int | None = None):
        """Notify main-bot about new post via Redis."""
        try:
            redis_client = aioredis.from_url("redis://redis:6379/0")
            
            event_data = {
                "channel_telegram_id": channel_id,
                "channel_username": channel_username,
                "channel_title": channel_title,
                "telegram_message_id": post_data["telegram_message_id"],
                "text": post_data.get("text"),
                "media_type": post_data.get("media_type"),
                "media_file_id": post_data.get("media_file_id"),
                "posted_at": post_data["posted_at"],
                "post_id": post_id,
            }
            
            await redis_client.publish("ppb:new_posts", json.dumps(event_data))
            await redis_client.close()
            
            logger.info(f"Real-time: Notified main-bot about post from @{channel_username}")
        except Exception as e:
            logger.error(f"Failed to notify about real-time post: {e}")
    
    async def start_listening(self):
        """Start listening for new messages (run event loop)."""
        await self.ensure_connected()
        logger.info("Starting Telethon event loop for real-time posts...")
        await self._client.run_until_disconnected()


# Singleton instance
_client: Optional[TelethonClientWrapper] = None


def get_client() -> TelethonClientWrapper:
    global _client
    if _client is None:
        _client = TelethonClientWrapper()
    return _client
