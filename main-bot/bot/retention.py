"""
Retention service - Sends nudge messages to inactive users.
Also listens for training completion events via Redis pub/sub.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import InputMediaPhoto, BufferedInputFile
import redis.asyncio as aioredis

from bot.config import get_settings
from bot.message_manager import MessageManager
from bot.api_client import get_core_api, get_user_bot
from bot.utils import escape_md
from bot.keyboards import get_feed_post_keyboard, get_feed_keyboard
from bot.texts import TEXTS, get_texts

logger = logging.getLogger(__name__)
settings = get_settings()
TELEGRAM_CAPTION_LIMIT = 1024


class RetentionService:
    """
    Background service that monitors user activity and sends
    retention messages when users are silent for too long.
    """
    
    def __init__(self, bot: Bot, message_manager: MessageManager):
        self.bot = bot
        self.message_manager = message_manager
        self._running = False
        self._task: asyncio.Task = None
        self._redis_task: asyncio.Task = None
        self._new_posts_task: asyncio.Task = None
    
    async def start(self):
        """Start the retention monitoring service."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        self._redis_task = asyncio.create_task(self._redis_subscriber())
        self._new_posts_task = asyncio.create_task(self._new_posts_subscriber())
        logger.info("Retention service started")
    
    async def stop(self):
        """Stop the retention monitoring service."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._redis_task:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                pass
        if self._new_posts_task:
            self._new_posts_task.cancel()
            try:
                await self._new_posts_task
            except asyncio.CancelledError:
                pass
        logger.info("Retention service stopped")
    
    async def _redis_subscriber(self):
        """Listen for training completion events from MiniApp via Redis pub/sub."""
        while self._running:
            try:
                redis_client = aioredis.from_url("redis://redis:6379/0")
                pubsub = redis_client.pubsub()
                await pubsub.subscribe("ppb:training_complete")
                logger.info("Redis subscriber started for training_complete events")
                
                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            telegram_id = data.get("telegram_id")
                            chat_id = data.get("chat_id", telegram_id)
                            
                            if telegram_id:
                                logger.info(f"Received training_complete for user {telegram_id}")
                                await self._handle_training_complete(chat_id, telegram_id)
                        except Exception as e:
                            logger.error(f"Error handling training_complete message: {e}")
                
                await pubsub.close()
                await redis_client.close()
            except Exception as e:
                logger.error(f"Redis subscriber error: {e}")
                await asyncio.sleep(5)  # Retry after 5 seconds
    
    async def _handle_training_complete(self, chat_id: int, user_id: int):
        """Handle training completion from MiniApp - send bonus offer message and initial best post."""
        from bot.keyboards import get_training_complete_keyboard
        from bot.handlers.training import send_initial_best_post
        
        api = get_core_api()
        
        # Get user language
        lang = await api.get_user_language(user_id)
        texts = get_texts(lang)
        
        # Get rated count from interactions
        interactions = await api.get_user_interactions(user_id)
        rated_count = len([i for i in interactions if i.get("interaction_type") in ("like", "dislike")]) if interactions else 0
        
        # Check if user has bonus channel
        user_channels = await api.get_user_channels(user_id)
        has_bonus = len(user_channels) > 0
        
        if has_bonus:
            # User already has bonus - show feed ready
            await self.message_manager.send_system(
                chat_id,
                texts.get("feed_ready"),
                reply_markup=get_feed_keyboard(lang, has_bonus),
                tag="menu",
            )
        else:
            # Offer bonus channel with rated count
            await self.message_manager.send_system(
                chat_id,
                texts.get("training_complete", rated_count=rated_count),
                reply_markup=get_training_complete_keyboard(lang),
                tag="menu",
            )
        
        logger.info(f"Sent training complete message to user {user_id}, rated_count={rated_count}")
        
        # Schedule initial best post after 60 seconds
        async def delayed_best_post():
            await asyncio.sleep(60)
            try:
                await send_initial_best_post(chat_id, user_id, self.message_manager)
            except Exception as e:
                logger.error(f"Error sending initial best post for user {user_id}: {e}")
        
        asyncio.create_task(delayed_best_post())
    
    async def _new_posts_subscriber(self):
        """Listen for new posts from user-bot and deliver to relevant users in real-time."""
        while self._running:
            try:
                redis_client = aioredis.from_url("redis://redis:6379/0")
                pubsub = redis_client.pubsub()
                await pubsub.subscribe("ppb:new_posts")
                logger.info("Redis subscriber started for new_posts events (real-time delivery)")
                
                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message["type"] == "message":
                        try:
                            post_data = json.loads(message["data"])
                            channel_username = post_data.get("channel_username")
                            logger.info(f"Received new post from {channel_username}")
                            await self._deliver_post_to_users(post_data)
                        except Exception as e:
                            logger.error(f"Error handling new_post message: {e}")
                
                await pubsub.close()
                await redis_client.close()
            except Exception as e:
                logger.error(f"New posts subscriber error: {e}")
                await asyncio.sleep(5)
    
    async def _deliver_post_to_users(self, post_data: dict):
        """Deliver a new post to all relevant trained users."""
        api = get_core_api()
        channel_username = post_data.get("channel_username", "").lstrip("@").lower()
        
        # Get all users
        users = await api.get_feed_users()
        logger.info(f"Real-time delivery: checking {len(users)} users for post from {channel_username}")
        
        # Get default training channels
        from bot.config import get_settings
        settings = get_settings()
        default_channels = [c.strip().lstrip("@").lower() for c in settings.default_training_channels.split(",") if c.strip()]
        
        for user in users:
            user_id = user.get("telegram_id")
            if not user_id:
                continue
            
            # Skip users still in training
            status = user.get("status", "").lower()
            if status == "training":
                logger.debug(f"User {user_id} still in training, skipping")
                continue
            
            # Check if user is trained
            if not user.get("is_trained"):
                logger.debug(f"User {user_id} not trained, skipping")
                continue
            
            # Check if user is subscribed to this channel (default channels or bonus)
            user_channels = await api.get_user_channels(user_id)
            user_channel_names = [c.get("username", "").lstrip("@").lower() for c in user_channels]
            
            all_user_channels = set(user_channel_names + default_channels)
            
            if channel_username not in all_user_channels:
                logger.debug(f"User {user_id} not subscribed to {channel_username}")
                continue
            
            logger.info(f"Real-time: Sending post from {channel_username} to user {user_id}")
            
            # Send the new post directly (it may not be indexed yet for best_posts)
            await self._send_realtime_post_direct(user_id, post_data)
            await asyncio.sleep(0.3)  # Rate limit
    
    async def _send_realtime_post_direct(self, user_id: int, post_data: dict):
        """Send a new post directly to user (from Redis data)."""
        try:
            api = get_core_api()
            user_bot = get_user_bot()
            lang = await api.get_user_language(user_id)
            
            channel_username = (post_data.get("channel_username") or "").lstrip("@")
            channel_title = post_data.get("channel_title") or channel_username
            msg_id = post_data.get("telegram_message_id")
            post_id = post_data.get("post_id") or post_data.get("id")
            text = escape_md(post_data.get("text") or "")[:500]
            media_type = post_data.get("media_type")
            
            # Build header with link to original post
            if channel_username and msg_id:
                header = f"📰 [{escape_md(channel_title)}](https://t.me/{channel_username}/{msg_id})\n\n"
            else:
                header = f"📰 *{escape_md(channel_title)}*\n\n"
            
            post_text = header + (text if text else "_[Media content]_")
            caption_fits = len(post_text) <= TELEGRAM_CAPTION_LIMIT
            sent_with_caption = False
            
            # Try to send with media
            if media_type == "photo" and channel_username and msg_id:
                try:
                    photo_bytes = await user_bot.get_photo(channel_username, msg_id)
                    if photo_bytes:
                        if caption_fits:
                            await self.message_manager.send_onetime(
                                user_id,
                                post_text,
                                reply_markup=get_feed_post_keyboard(post_id, lang) if post_id else None,
                                tag="realtime_post",
                                photo_bytes=photo_bytes,
                                photo_filename=f"{msg_id}.jpg",
                            )
                            sent_with_caption = True
                        else:
                            input_file = BufferedInputFile(photo_bytes, filename=f"{msg_id}.jpg")
                            await self.message_manager.bot.send_photo(
                                chat_id=user_id,
                                photo=input_file,
                            )
                except Exception as e:
                    logger.warning(f"Failed to get photo for realtime post: {e}")
            
            elif media_type == "video" and channel_username and msg_id:
                try:
                    video_bytes = await user_bot.get_video(channel_username, msg_id)
                    if video_bytes:
                        input_file = BufferedInputFile(video_bytes, filename=f"{msg_id}.mp4")
                        if caption_fits:
                            await self.message_manager.bot.send_video(
                                chat_id=user_id,
                                video=input_file,
                                caption=post_text,
                                parse_mode="Markdown",
                                reply_markup=get_feed_post_keyboard(post_id, lang) if post_id else None,
                            )
                            sent_with_caption = True
                        else:
                            await self.message_manager.bot.send_video(
                                chat_id=user_id,
                                video=input_file,
                            )
                except Exception as e:
                    logger.warning(f"Failed to get video for realtime post: {e}")
            
            if not sent_with_caption:
                await self.message_manager.send_onetime(
                    user_id,
                    post_text,
                    reply_markup=get_feed_post_keyboard(post_id, lang) if post_id else None,
                    tag="realtime_post",
                )
            logger.info(f"Sent real-time post to user {user_id}")
        except Exception as e:
            logger.error(f"Error sending real-time post to {user_id}: {e}")
    
    async def _send_realtime_post(self, user_id: int, post: dict):
        """Send a single post to user in real-time."""
        try:
            lang = await get_core_api().get_user_language(user_id)
            
            channel_title = escape_md(post.get("channel_title", "Unknown"))
            channel_username = (post.get("channel_username") or "").lstrip("@")
            msg_id = post.get("telegram_message_id")
            text = escape_md(post.get("text") or "")[:500]
            
            # Build header
            if channel_username and msg_id:
                header = f"📰 [{channel_title}](https://t.me/{channel_username}/{msg_id})\n\n"
            else:
                header = f"📰 *{channel_title}*\n\n"
            
            post_text = header + text
            
            # Send with rating buttons
            await self.message_manager.send_onetime(
                user_id,
                post_text,
                reply_markup=get_feed_post_keyboard(post.get("id")),
                tag="realtime_post",
            )
            logger.info(f"Sent real-time post to user {user_id}")
        except Exception as e:
            logger.error(f"Error sending real-time post to {user_id}: {e}")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                # First, push fresh feed posts to eligible users
                await self._push_feed_updates()
                # Then, handle classic retention nudges for inactive users
                await self._check_inactive_users()
            except Exception as e:
                logger.error(f"Error in retention loop: {e}")
            
            await asyncio.sleep(settings.retention_check_interval)
    
    async def _check_inactive_users(self):
        """Check for inactive users and send nudge messages.
        
        Queries the API for users who:
        1. Are trained (status = 'trained' or 'active')
        2. Haven't been active since the threshold
        3. Haven't received a nudge recently
        """
        api = get_core_api()
        
        logger.debug(f"Checking for inactive users (threshold: {settings.retention_silence_threshold}s)")
        
        # Get inactive users from API
        inactive_users = await api.get_inactive_users(
            silence_threshold_seconds=settings.retention_silence_threshold
        )
        
        if not inactive_users:
            logger.debug("No inactive users found")
            return
        
        logger.info(f"Found {len(inactive_users)} inactive users for nudging")
        
        for user in inactive_users:
            user_id = user.get("telegram_id")
            if not user_id:
                continue
            
            # Don't send nudges if user is in training mode
            if user.get("status") == "training":
                continue
            
            try:
                # Send nudge with best post
                await self.send_nudge(user_id, user_id)
                
                # Mark nudge as sent to avoid spamming
                await api.mark_nudge_sent(user_id)
                
                logger.info(f"Sent retention nudge to user {user_id}")
                
                # Small delay between nudges to avoid rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error sending nudge to user {user_id}: {e}")
    
    async def _push_feed_updates(self):
        """Send best feed posts to users eligible for automatic delivery."""
        api = get_core_api()
        users = await api.get_feed_users()

        for user in users:
            user_id = user.get("telegram_id")
            if not user_id:
                continue

            # Don't send posts if user is in training mode
            if user.get("status") == "training":
                continue

            posts = await api.get_best_posts(user_id, limit=1)
            if not posts:
                continue

            post = posts[0]
            await self._send_feed_post(user_id, post)
    
    async def send_nudge(self, chat_id: int, user_telegram_id: int):
        """Send a retention nudge message with a relevant post."""
        api = get_core_api()
        
        # Get best post for user
        posts = await api.get_best_posts(user_telegram_id, limit=1)
        
        if not posts:
            logger.debug(f"No posts to send as nudge for user {user_telegram_id}")
            return
        
        post = posts[0]
        
        # Format nudge message
        channel_title = escape_md(post.get("channel_title", "Unknown"))
        text = escape_md(post.get("text") or "")
        
        nudge_text = f"{TEXTS['retention_nudge']}\n\n"
        nudge_text += f"📰 *{channel_title}*\n\n"
        nudge_text += text if text else "_[Check out this post]_"

        caption_fits = len(nudge_text) <= TELEGRAM_CAPTION_LIMIT
        sent_with_caption = False

        # Try to fetch photo(s) if available
        if post.get("media_type") == "photo":
            channel_username = post.get("channel_username")
            media_ids_str = post.get("media_file_id") or ""

            media_ids: list[int] = []
            if media_ids_str:
                for part in media_ids_str.split(","):
                    part = part.strip()
                    if part.isdigit():
                        media_ids.append(int(part))
            else:
                msg_id = post.get("telegram_message_id")
                if isinstance(msg_id, int):
                    media_ids.append(msg_id)

            if channel_username and media_ids:
                user_bot = get_user_bot()
                if len(media_ids) > 1:
                    # Album - send as media group, text will remain separate
                    tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    media_items: list[InputMediaPhoto] = []
                    for mid, res in zip(media_ids, results):
                        if isinstance(res, Exception) or not res:
                            continue
                        photo_bytes = res
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        media_items.append(InputMediaPhoto(media=input_file))
                    if media_items:
                        await self.message_manager.bot.send_media_group(
                            chat_id=user_telegram_id,
                            media=media_items,
                        )
                else:
                    mid = media_ids[0]
                    try:
                        photo_bytes = await user_bot.get_photo(channel_username, mid)
                    except Exception:
                        photo_bytes = None
                    if photo_bytes:
                        if caption_fits:
                            await self.message_manager.send_onetime(
                                user_telegram_id,
                                nudge_text,
                                reply_markup=get_feed_post_keyboard(post.get("id")),
                                tag="retention_post",
                                photo_bytes=photo_bytes,
                                photo_filename=f"{mid}.jpg",
                            )
                            sent_with_caption = True
                        else:
                            input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                            await self.message_manager.bot.send_photo(
                                chat_id=user_telegram_id,
                                photo=input_file,
                            )

        if not sent_with_caption:
            await self.message_manager.send_onetime(
                user_telegram_id,
                nudge_text,
                reply_markup=get_feed_post_keyboard(post.get("id")),
                tag="retention_post",
            )
        
        # Log the nudge
        await api.create_log(user_telegram_id, "retention_nudge_sent", f"post_id={post.get('id')}")
        logger.info(f"Sent retention nudge to user {user_telegram_id}")

    async def _send_feed_post(self, user_telegram_id: int, post: dict):
        """Send a regular feed post to the user (used for automatic delivery)."""
        channel_title = escape_md(post.get("channel_title", "Unknown"))
        text = escape_md(post.get("text") or "")

        feed_text = f"📰 *{channel_title}*\n\n"
        feed_text += text if text else "_[Media content]_"

        caption_fits = len(feed_text) <= TELEGRAM_CAPTION_LIMIT
        sent_with_caption = False

        # Try to fetch photo(s) if available, similar to send_nudge
        if post.get("media_type") == "photo":
            channel_username = post.get("channel_username")
            media_ids_str = post.get("media_file_id") or ""

            media_ids: list[int] = []
            if media_ids_str:
                for part in media_ids_str.split(","):
                    part = part.strip()
                    if part.isdigit():
                        media_ids.append(int(part))
            else:
                msg_id = post.get("telegram_message_id")
                if isinstance(msg_id, int):
                    media_ids.append(msg_id)

            if channel_username and media_ids:
                user_bot = get_user_bot()
                if len(media_ids) > 1:
                    # Album - send as media group, text will remain separate
                    tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    media_items: list[InputMediaPhoto] = []
                    for mid, res in zip(media_ids, results):
                        if isinstance(res, Exception) or not res:
                            continue
                        photo_bytes = res
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        media_items.append(InputMediaPhoto(media=input_file))
                    if media_items:
                        await self.message_manager.bot.send_media_group(
                            chat_id=user_telegram_id,
                            media=media_items,
                        )
                else:
                    mid = media_ids[0]
                    try:
                        photo_bytes = await user_bot.get_photo(channel_username, mid)
                    except Exception:
                        photo_bytes = None
                    if photo_bytes:
                        if caption_fits:
                            await self.message_manager.send_onetime(
                                user_telegram_id,
                                feed_text,
                                reply_markup=get_feed_post_keyboard(post.get("id")),
                                tag="feed_post",
                                photo_bytes=photo_bytes,
                                photo_filename=f"{mid}.jpg",
                            )
                            sent_with_caption = True
                        else:
                            input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                            await self.message_manager.bot.send_photo(
                                chat_id=user_telegram_id,
                                photo=input_file,
                            )

        if not sent_with_caption:
            await self.message_manager.send_onetime(
                user_telegram_id,
                feed_text,
                reply_markup=get_feed_post_keyboard(post.get("id")),
                tag="feed_post",
            )
