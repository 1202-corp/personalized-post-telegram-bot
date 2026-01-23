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
from bot.services import get_core_api, get_user_bot
from bot.core.message_manager import MessageManager
from bot.core import get_feed_post_keyboard

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
            # Format the post - HTML format
            channel_username = post.get("channel_username", "").lstrip("@")
            msg_id = post.get("telegram_message_id")
            text = post.get("text", "")
            escaped_text = html.escape(text)
            
            # Create header with link (HTML)
            if channel_username and msg_id:
                header = f"🆕 Новый пост в <a href=\"https://t.me/{channel_username}/{msg_id}\">@{channel_username}</a>\n\n"
            else:
                header = "🆕 Новый пост\n\n"
            
            full_text = header + escaped_text
            
            # Send based on media type
            media_type = post.get("media_type")
            
            if media_type == "photo":
                # Get photo from user-bot
                user_bot = get_user_bot()
                photo_bytes = await user_bot.get_photo(channel_username, msg_id)
                
                if photo_bytes:
                    await self.message_manager.send_regular(
                        chat_id=user_id,
                        text=full_text[:1024],
                        reply_markup=get_feed_post_keyboard(post.get("id"), lang),
                        photo_bytes=photo_bytes,
                        photo_filename=f"{msg_id}.jpg",
                        tag="realtime_post"
                    )
                else:
                    await self._send_text_post(user_id, full_text, post, lang)
            else:
                await self._send_text_post(user_id, full_text, post, lang)
            
            self._notified_posts.add(post.get("id"))
            logger.info(f"Sent real-time post {post.get('id')} to user {user_id}")
            
        except Exception as e:
            logger.error(f"Error sending real-time post to user {user_id}: {e}")
    
    async def _send_text_post(self, user_id: int, text: str, post: dict, lang: str):
        """Send a text-only post."""
        await self.message_manager.send_regular(
            chat_id=user_id,
            text=text,
            reply_markup=get_feed_post_keyboard(post.get("id"), lang),
            tag="realtime_post"
        )


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
