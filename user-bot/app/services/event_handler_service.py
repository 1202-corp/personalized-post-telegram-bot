"""
Service for handling real-time Telegram events.
"""
import asyncio
import logging
from typing import Dict, List
from datetime import datetime

from telethon import events
from telethon.tl.types import Message

from app.core.utils import get_message_html
from app.types import (
    TelethonServiceProtocol,
    SyncServiceProtocol,
    NotificationServiceProtocol,
    PostDataDict,
)

logger = logging.getLogger(__name__)


class EventHandlerService:
    """Service for handling real-time Telegram events."""
    
    def __init__(
        self,
        telethon_service: TelethonServiceProtocol,
        sync_service: SyncServiceProtocol,
        notification_service: NotificationServiceProtocol
    ):
        """
        Initialize event handler service.
        
        Args:
            telethon_service: Telethon service instance
            sync_service: Sync service instance
            notification_service: Notification service instance
        """
        self.telethon_service = telethon_service
        self.sync_service = sync_service
        self.notification_service = notification_service
        self._event_handler_registered = False
        self._pending_albums: Dict[int, List[Message]] = {}
        self._album_timers: Dict[int, asyncio.Task] = {}
    
    async def register_event_handler(self) -> None:
        """Register event handler for new messages in channels."""
        if self._event_handler_registered:
            return
        
        # Get client from telethon_service
        client = self.telethon_service.client
        if not client:
            logger.error("Cannot register event handler: Telethon client not available")
            return
        
        @client.on(events.NewMessage(chats=None))
        async def handle_new_message(event):
            """Handle new messages from channels in real-time."""
            try:
                # Only process channel posts
                if not event.is_channel:
                    return
                
                message = event.message
                
                # Skip old messages (only process messages from last 60 seconds)
                if not self._should_process_message(message):
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
                    await self._handle_album_message(
                        message,
                        message.grouped_id,
                        channel_id,
                        channel_username,
                        channel_title
                    )
                    return
                
                logger.info(f"Real-time: New post in @{channel_username}")
                
                # Prepare post data for single message
                post_data = self._create_post_data(message, channel_id, channel_username, channel_title)
                
                # Sync to core-api and get post_id
                post_id = await self.sync_service.sync_realtime_post(
                    channel_id,
                    channel_username,
                    channel_title,
                    post_data
                )
                # Save channel avatar and description on sync (idempotent overwrite)
                try:
                    avatar_bytes = await self.telethon_service.get_channel_avatar_bytes(channel_username)
                    if avatar_bytes:
                        await self.sync_service.upload_channel_avatar(channel_id, avatar_bytes)
                except Exception as av_err:
                    logger.debug(f"Channel avatar upload skipped for @{channel_username}: {av_err}")
                try:
                    description = await self.telethon_service.get_channel_description(channel_username)
                    await self.sync_service.set_channel_description(channel_id, description)
                except Exception as desc_err:
                    logger.debug(f"Channel description upload skipped for @{channel_username}: {desc_err}")
                # Notify main-bot via Redis for instant delivery
                await self.notification_service.notify_realtime_post(
                    channel_id,
                    channel_username,
                    channel_title,
                    post_data,
                    post_id
                )
                
            except Exception as e:
                logger.error(f"Error handling real-time message: {e}")
        
        self._event_handler_registered = True
        logger.info("Real-time event handler registered for channel posts")
    
    def _should_process_message(self, message: Message) -> bool:
        """
        Check if message should be processed.
        
        Only processes messages from last 60 seconds.
        
        Args:
            message: Telethon Message object
            
        Returns:
            True if message should be processed
        """
        if not message.date:
            return True  # Process messages without date
        
        message_age = (datetime.utcnow() - message.date.replace(tzinfo=None)).total_seconds()
        return message_age <= 60
    
    async def _handle_album_message(
        self,
        message: Message,
        grouped_id: int,
        channel_id: int,
        channel_username: str,
        channel_title: str
    ) -> None:
        """
        Handle album (grouped) message.
        
        Args:
            message: Message object
            grouped_id: Album grouped ID
            channel_id: Channel ID
            channel_username: Channel username
            channel_title: Channel title
        """
        if grouped_id not in self._pending_albums:
            self._pending_albums[grouped_id] = []
        self._pending_albums[grouped_id].append(message)
        
        # Start/restart timer for this album
        if grouped_id in self._album_timers:
            self._album_timers[grouped_id].cancel()
        self._album_timers[grouped_id] = asyncio.create_task(
            self._process_album(grouped_id, channel_id, channel_username, channel_title)
        )
    
    async def _process_album(
        self,
        grouped_id: int,
        channel_id: int,
        channel_username: str,
        channel_title: str
    ) -> None:
        """
        Process collected album messages.
        
        Args:
            grouped_id: Album grouped ID
            channel_id: Channel ID
            channel_username: Channel username
            channel_title: Channel title
        """
        await asyncio.sleep(1.5)  # Wait for all album messages to arrive
        
        if grouped_id not in self._pending_albums:
            return
        
        messages = self._pending_albums.pop(grouped_id, [])
        self._album_timers.pop(grouped_id, None)
        
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
        text = get_message_html(main_msg)
        all_ids = [m.id for m in messages]
        media_file_id = ",".join(str(mid) for mid in all_ids)
        
        # Get media type from telethon_service
        if hasattr(self.telethon_service, 'get_media_type'):
            media_type = self.telethon_service.get_media_type(main_msg)
        else:
            media_type = None
        
        post_data: PostDataDict = {
            "telegram_message_id": main_msg.id,
            "text": text,
            "media_type": media_type,
            "media_file_id": media_file_id,
            "posted_at": main_msg.date.isoformat() if main_msg.date else datetime.utcnow().isoformat(),
        }
        
        logger.info(f"Real-time: Album with {len(messages)} photos in @{channel_username}")
        
        # Sync to core-api and get post_id
        post_id = await self.sync_service.sync_realtime_post(
            channel_id,
            channel_username,
            channel_title,
            post_data
        )
        try:
            avatar_bytes = await self.telethon_service.get_channel_avatar_bytes(channel_username)
            if avatar_bytes:
                await self.sync_service.upload_channel_avatar(channel_id, avatar_bytes)
        except Exception as av_err:
            logger.debug(f"Channel avatar upload skipped for @{channel_username}: {av_err}")
        try:
            description = await self.telethon_service.get_channel_description(channel_username)
            await self.sync_service.set_channel_description(channel_id, description)
        except Exception as desc_err:
            logger.debug(f"Channel description upload skipped for @{channel_username}: {desc_err}")
        # Notify main-bot
        await self.notification_service.notify_realtime_post(
            channel_id,
            channel_username,
            channel_title,
            post_data,
            post_id
        )
    
    def _create_post_data(
        self,
        message: Message,
        channel_id: int,
        channel_username: str,
        channel_title: str
    ) -> PostDataDict:
        """
        Create post data dictionary from message.
        
        Args:
            message: Telethon Message object
            channel_id: Channel ID
            channel_username: Channel username
            channel_title: Channel title
            
        Returns:
            Post data dictionary
        """
        text = get_message_html(message)
        if hasattr(self.telethon_service, 'get_media_type'):
            media_type = self.telethon_service.get_media_type(message)
        else:
            media_type = None
        
        return {
            "telegram_message_id": message.id,
            "text": text,
            "media_type": media_type,
            "media_file_id": str(message.id) if message.media else None,
            "posted_at": message.date.isoformat() if message.date else datetime.utcnow().isoformat(),
        }

