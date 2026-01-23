"""
Post service for sending posts with media to Telegram chats.

Unifies post sending logic from handlers to avoid duplication.
"""

import logging
from typing import Optional, List, Tuple, Any
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, BufferedInputFile, LinkPreviewOptions

from bot.types import PostData, PostServiceProtocol, MediaServiceProtocol, UserBotServiceProtocol
from bot.core.message_manager import MessageManager
from bot.utils import format_post_text, parse_media_ids, TELEGRAM_CAPTION_LIMIT

logger = logging.getLogger(__name__)


class PostService:
    """Service for sending posts with media."""
    
    def __init__(
        self,
        message_manager: MessageManager,
        media_service: MediaServiceProtocol,
        user_bot: UserBotServiceProtocol
    ):
        self.message_manager = message_manager
        self.media_service = media_service
        self.user_bot = user_bot
    
    async def send_post(
        self,
        chat_id: int,
        post: PostData,
        keyboard: Optional[InlineKeyboardMarkup] = None,
        tag: str = "post",
        message_type: str = "ephemeral",
        include_relevance: bool = False,
    ) -> Tuple[bool, List[int]]:
        """
        Send a post with optional media to chat.
        
        Handles single photos, photo albums, and text-only posts.
        Uses caption when text fits within Telegram limit.
        
        If post["text"] already contains formatted text (e.g., with hyperlinks),
        it will be used as-is. Otherwise, format_post_text will be called.
        
        Args:
            chat_id: Telegram chat ID
            post: Post data dict (may contain pre-formatted text)
            keyboard: Optional inline keyboard
            tag: Message tag for message_manager
            message_type: Type of message (temporary, regular, system)
            include_relevance: Include relevance score in text (only if text not pre-formatted)
        
        Returns:
            Tuple of (sent_with_caption: bool, media_message_ids: List[int])
        """
        # Check if text is already formatted (contains HTML links or special formatting)
        post_text = post.get("text", "")
        if not post_text or (not post_text.startswith("📰") and not "<a href" in post_text):
            # Text not formatted, use format_post_text
            post_text = format_post_text(post, include_relevance=include_relevance)
        caption_fits = len(post_text) <= TELEGRAM_CAPTION_LIMIT
        sent_with_caption = False
        media_message_ids: List[int] = []
        
        # Determine send method based on message_type
        if message_type == "temporary" or message_type == "ephemeral":
            send_method = self.message_manager.send_temporary
        elif message_type == "regular" or message_type == "onetime":
            send_method = self.message_manager.send_regular
        else:
            send_method = self.message_manager.send_system
        
        # Handle media posts
        if post.get("media_type") == "photo":
            channel_username = post.get("channel_username", "").lstrip("@")
            media_ids = parse_media_ids(post)
            
            if channel_username and media_ids:
                if len(media_ids) > 1:
                    # Send album
                    media_items: List[InputMediaPhoto] = []
                    for mid in media_ids:
                        try:
                            # Try cache first
                            cached_photos = await self.media_service.get_cached_photos(
                                chat_id, post.get("id", 0)
                            )
                            if cached_photos and mid in media_ids[:len(cached_photos)]:
                                idx = media_ids.index(mid)
                                if idx < len(cached_photos):
                                    photo_bytes = cached_photos[idx]
                                else:
                                    photo_bytes = await self.user_bot.get_photo(channel_username, mid)
                            else:
                                photo_bytes = await self.user_bot.get_photo(channel_username, mid)
                        except Exception:
                            photo_bytes = None
                        
                        if not photo_bytes:
                            continue
                        
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        media_items.append(InputMediaPhoto(media=input_file))
                    
                    if media_items:
                        msgs = await self.message_manager.bot.send_media_group(
                            chat_id=chat_id,
                            media=media_items,
                        )
                        media_message_ids.extend(m.message_id for m in msgs)
                else:
                    # Single photo
                    mid = media_ids[0]
                    try:
                        # Try cache first
                        cached_photo = await self.media_service.get_cached_photo(
                            chat_id, post.get("id", 0)
                        )
                        if cached_photo:
                            photo_bytes = cached_photo
                        else:
                            photo_bytes = await self.user_bot.get_photo(channel_username, mid)
                    except Exception:
                        photo_bytes = None
                    
                    if photo_bytes:
                        if caption_fits:
                            # Delete previous message with same tag
                            if message_type == "temporary" or message_type == "ephemeral":
                                await self.message_manager.delete_temporary(chat_id, tag=tag)
                            
                            await send_method(
                                chat_id,
                                post_text,
                                reply_markup=keyboard,
                                tag=tag,
                                photo_bytes=photo_bytes,
                                photo_filename=f"{mid}.jpg",
                            )
                            sent_with_caption = True
                        else:
                            # Send photo separately
                            input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                            msg = await self.message_manager.bot.send_photo(
                                chat_id=chat_id,
                                photo=input_file,
                            )
                            media_message_ids.append(msg.message_id)
        
        # Send text message if not sent with caption
        if not sent_with_caption:
            if message_type == "temporary" or message_type == "ephemeral":
                await self.message_manager.delete_temporary(chat_id, tag=tag)
            
            await send_method(
                chat_id,
                post_text,
                reply_markup=keyboard,
                tag=tag,
            )
        
        return sent_with_caption, media_message_ids
    
    async def cleanup_media_messages(
        self,
        chat_id: int,
        message_ids: List[int]
    ) -> None:
        """Clean up media messages by IDs."""
        for mid in message_ids:
            try:
                await self.message_manager.bot.delete_message(chat_id, mid)
            except Exception:
                pass

