"""
Real-time feed service.

Monitors channels for new posts and sends relevant ones to users.
Uses webhooks from user-bot to receive notifications about new posts.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Set
from aiogram import Bot

import html
from bot.services import get_core_api, get_user_bot, get_post_cache
from bot.core.message_manager import MessageManager
from bot.core import get_feed_post_keyboard, get_post_open_in_channel_keyboard, get_texts

logger = logging.getLogger(__name__)


class RealtimeFeedService:
    """
    Service for delivering new posts to users in real-time.
    
    Flow:
    1. User-bot scrapes channels periodically or via webhook
    2. New posts are saved to DB with embeddings
    3. This service checks for new posts and sends to relevant users
    """
    
    def __init__(self, bot: Bot, message_manager: MessageManager):
        self.bot = bot
        self.message_manager = message_manager
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_check: datetime = datetime.utcnow()
        self._notified_posts: Set[int] = set()  # Track sent post IDs
        self._check_interval = 60  # Check every minute
    
    async def start(self):
        """Start the real-time feed service."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Real-time feed service started")
    
    async def stop(self):
        """Stop the real-time feed service."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Real-time feed service stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_new_posts()
            except Exception as e:
                logger.error(f"Error in real-time feed monitor: {e}")
            
            await asyncio.sleep(self._check_interval)
    
    async def _check_new_posts(self):
        """Check for new posts and notify relevant users."""
        api = get_core_api()
        
        # Get posts created since last check
        # This would require a new API endpoint to get recent posts
        # For now, we'll use the existing best posts endpoint
        
        # Get all trained users
        # In production, this should be paginated and optimized
        try:
            # This is a simplified approach
            # A full implementation would track last seen post per user
            pass
        except Exception as e:
            logger.error(f"Error checking new posts: {e}")
    
    async def notify_user_new_post(
        self,
        user_id: int,
        post: dict,
        lang: str = "en_US",
    ):
        """Send a new post notification to a user."""
        try:
            # Format the post: header (safe HTML) + body as HTML from API
            channel_username = post.get("channel_username", "").lstrip("@")
            channel_title = post.get("channel_title") or f"@{channel_username}"
            msg_id = post.get("telegram_message_id")
            text = post.get("text", "") or ""
            media_type = post.get("media_type")
            media_file_id = post.get("media_file_id")
            
            # Create header with link to post
            if channel_username and msg_id:
                # For media groups, link to first message
                first_msg_id = msg_id
                if media_file_id and "," in str(media_file_id):
                    first_msg_id = media_file_id.split(",")[0]
                header = f'🆕 <a href="https://t.me/{channel_username}/{first_msg_id}">{html.escape(channel_title)}</a>\n\n'
            else:
                header = f"🆕 {html.escape(channel_title)}\n\n"
            
            full_text = header + text
            
            # Handle media groups (multiple photos)
            if media_type == "media_group" and media_file_id:
                await self._send_media_group_post(user_id, full_text, post, lang, channel_username, media_file_id)
            elif media_type == "photo":
                await self._send_photo_post(user_id, full_text, post, lang, channel_username, msg_id, use_video=False)
            elif media_type == "video":
                # Video is never sent as video: first frame + play overlay as photo (JPEG)
                await self._send_photo_post(user_id, full_text, post, lang, channel_username, msg_id, use_video=True)
            else:
                await self._send_text_post(user_id, full_text, post, lang)
            
            self._notified_posts.add(post.get("id"))
            logger.info(f"Sent real-time post {post.get('id')} to user {user_id}")
            
        except Exception as e:
            logger.error(f"Error sending real-time post to user {user_id}: {e}")
    
    def _post_url_from_post(self, post: dict) -> Optional[str]:
        """Build link to original post in channel (same as in post text header)."""
        channel_username = (post.get("channel_username") or "").lstrip("@")
        msg_id = post.get("telegram_message_id")
        media_file_id = post.get("media_file_id")
        if media_file_id and "," in str(media_file_id):
            first_msg_id = (media_file_id.split(",")[0] or "").strip()
        else:
            first_msg_id = str(msg_id) if msg_id is not None else None
        if channel_username and first_msg_id:
            return f"https://t.me/{channel_username}/{first_msg_id}"
        return None

    async def _send_text_post(self, user_id: int, text: str, post: dict, lang: str):
        """Send a text-only post with buttons as separate message."""
        # Send post without buttons
        post_url = self._post_url_from_post(post)
        post_open_kb = get_post_open_in_channel_keyboard(post_url, lang)
        post_msg = await self.message_manager.send_regular(
            chat_id=user_id,
            text=text,
            reply_markup=post_open_kb,
            tag="realtime_post",
            add_main_menu=True,
            lang=lang,
        )
        post_message_id = post_msg.message_id if post_msg else None
        question_text = get_texts(lang).get("feed_post_question", "👆 Как вам данный пост?")
        await self.message_manager.send_regular(
            chat_id=user_id,
            text=question_text,
            reply_markup=get_feed_post_keyboard(post.get("id"), lang, post_message_id=post_message_id),
            tag="realtime_post_buttons",
            add_main_menu=True,
            lang=lang,
        )
    
    async def _send_photo_post(
        self, user_id: int, text: str, post: dict, lang: str,
        channel_username: str, msg_id: int, *, use_video: bool = False
    ):
        """Send a post with a single photo (or video as thumbnail+play JPEG). 'Open in channel' on post message."""
        try:
            post_url = f"https://t.me/{channel_username}/{msg_id}" if channel_username and msg_id else None
            post_open_kb = get_post_open_in_channel_keyboard(post_url, lang)
            post_id = post.get("id")
            cached_file_id = None
            if post_id:
                cache = get_post_cache()
                content = await cache.get_post_content(post_id)
                if content:
                    cached_file_id = content.get("telegram_file_id")
            if cached_file_id:
                msg = await self.message_manager.send_regular(
                    chat_id=user_id,
                    text=text[:1024],
                    photo=cached_file_id,
                    reply_markup=post_open_kb,
                    tag="realtime_post",
                    add_main_menu=True,
                    lang=lang,
                )
            else:
                user_bot = get_user_bot()
                if use_video:
                    # get_video returns JPEG (first frame + play overlay)
                    photo_bytes = await user_bot.get_video(channel_username, msg_id)
                else:
                    photo_bytes = await user_bot.get_photo(channel_username, msg_id)
                if photo_bytes:
                    msg = await self.message_manager.send_regular(
                        chat_id=user_id,
                        text=text[:1024],
                        photo_bytes=photo_bytes,
                        photo_filename=f"{msg_id}.jpg",
                        reply_markup=post_open_kb,
                        tag="realtime_post",
                        add_main_menu=True,
                        lang=lang,
                    )
                    if post_id and msg and msg.photo:
                        cache = get_post_cache()
                        await cache.set_post_content(post_id, telegram_file_id=msg.photo[-1].file_id)
                else:
                    msg = None
            if msg:
                post_message_id = msg.message_id
                question_text = get_texts(lang).get("feed_post_question", "👆 Как вам данный пост?")
                await self.message_manager.send_regular(
                    chat_id=user_id,
                    text=question_text,
                    reply_markup=get_feed_post_keyboard(post.get("id"), lang, post_message_id=post_message_id),
                    tag="realtime_post_buttons",
                    add_main_menu=True,
                    lang=lang,
                )
            else:
                await self._send_text_post(user_id, text, post, lang)
        except Exception as e:
            logger.warning(f"Failed to send photo, falling back to text: {e}")
            await self._send_text_post(user_id, text, post, lang)
    
    async def _send_media_group_post(
        self, user_id: int, text: str, post: dict, lang: str,
        channel_username: str, media_file_id: str
    ):
        """Send a post with multiple photos (media group) - sends first photo with caption."""
        try:
            # For media groups, send the first photo with the caption
            msg_ids = [int(mid) for mid in media_file_id.split(",")]
            first_msg_id = msg_ids[0] if msg_ids else None
            
            if first_msg_id:
                await self._send_photo_post(user_id, text, post, lang, channel_username, first_msg_id)
            else:
                await self._send_text_post(user_id, text, post, lang)
        except Exception as e:
            logger.warning(f"Failed to send media group, falling back to text: {e}")
            await self._send_text_post(user_id, text, post, lang)


# Webhook endpoint for user-bot to notify about new posts
async def handle_new_post_webhook(post_data: dict, feed_service: RealtimeFeedService):
    """
    Handle webhook notification about a new post.
    
    This would be called by user-bot when it detects a new post in a channel.
    """
    api = get_core_api()
    
    # Get users subscribed to this channel
    channel_id = post_data.get("channel_id")
    
    # Get relevant users (those subscribed to this channel and trained)
    # This requires a new API endpoint
    
    # For each relevant user, check if post matches their preferences
    # and send if relevance score is high enough
    
    pass
