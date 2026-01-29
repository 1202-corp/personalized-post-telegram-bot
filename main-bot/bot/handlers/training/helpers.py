"""Helper functions for training handlers."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List

from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

from bot.core import MessageManager, get_texts, get_settings
from bot.core.states import TrainingStates
from bot.services import get_core_api, get_user_bot, get_post_cache
from bot.services.media_service import MediaService
import html
import base64
from bot.utils import TELEGRAM_CAPTION_LIMIT
from bot.core import (
    get_training_post_keyboard, get_feed_keyboard, get_training_complete_keyboard,
    get_bonus_channel_keyboard,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize services (will be injected via dependency injection in future)
_media_service: MediaService | None = None


def _get_media_service() -> MediaService:
    """Get or create media service instance."""
    global _media_service
    if _media_service is None:
        _media_service = MediaService(get_user_bot())
    return _media_service


from bot.utils import get_user_lang as _get_user_lang


async def _prefetch_post_content(
    post_id: int,
    channel_username: str,
    message_id: int
) -> None:
    """
    Prefetch post content (text and media) and cache it in Redis.
    
    Args:
        post_id: Post ID
        channel_username: Channel username
        message_id: Telegram message ID
    """
    try:
        # Check cache first
        post_cache = get_post_cache()
        cached = await post_cache.get_post_content(post_id)
        
        if cached:
            # Already cached, skip
            return
        
        # Fetch from user-bot
        user_bot = get_user_bot()
        full_content = await user_bot.get_post_full_content(channel_username, message_id)
        
        if full_content:
            # Cache the content
            await post_cache.set_post_content(
                post_id=post_id,
                text=full_content.get("text"),
                media_type=full_content.get("media_type"),
                media_data=full_content.get("media_data")  # base64 string
            )
            logger.debug(f"Prefetched and cached post content (post_id={post_id})")
    except Exception as e:
        logger.error(f"Error prefetching post content (post_id={post_id}): {e}")


async def _start_training_session(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
    state: FSMContext,
) -> None:
    """Initialize and show the first training post."""
    data = await state.get_data()
    posts = data.get("training_posts", [])
    
    # Prefetch first two posts (index 0 and 1) in background
    if posts:
        post_cache = get_post_cache()
        for i in [0, 1]:
            if i < len(posts):
                post = posts[i]
                post_id = post.get("id")
                channel_username = post.get("channel_username", "").lstrip("@")
                msg_id = post.get("telegram_message_id")
                
                if post_id and channel_username and msg_id:
                    # Check if already cached
                    cached = await post_cache.get_post_content(post_id)
                    if not cached:
                        # Prefetch in background
                        asyncio.create_task(
                            _prefetch_post_content(post_id, channel_username, msg_id)
                        )

    await show_training_post(chat_id, message_manager, state)


async def _bonus_channel_nudge_watcher(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
) -> None:
    """Напоминания забрать бонусный канал через 1 мин, 1 час и 1 день."""
    api = get_core_api()
    thresholds = [60, 3600, 24 * 3600]

    for stage, delay in enumerate(thresholds, start=1):
        try:
            await asyncio.sleep(delay)

            user = await api.get_user(user_id)
            if not user:
                break

            if user.get("bonus_channels_count", 0) >= 1:
                break

            lang = await _get_user_lang(user_id)
            texts = get_texts(lang)
            key = f"bonus_nudge_{stage}"
            text = texts.get(key)
            if not text:
                text = "🎁 You still have a free bonus channel to claim."

            await message_manager.send_temporary(
                chat_id,
                text,
                reply_markup=get_bonus_channel_keyboard(lang),
                tag="bonus_nudge",
            )
        except Exception as e:
            logger.error(f"Error in bonus channel nudge watcher for user {user_id}: {e}")
            break


async def show_training_post(chat_id: int, message_manager: MessageManager, state: FSMContext):
    """Display current training post for rating.
    
    Sends two messages:
    1. Regular message - post content (text/media) without buttons
    2. Temporary message - progress text + rating buttons
    """
    from aiogram.types import InputMediaPhoto, BufferedInputFile
    
    data = await state.get_data()
    posts = data.get("training_posts", [])
    queue = data.get("training_queue", [])
    user_id = data.get("user_id")
    
    # Get current post index from queue (if using queue) or fallback to current_post_index
    if queue:
        index = queue[0]  # First item in queue is current post
    else:
        index = data.get("current_post_index", 0)
    
    if index >= len(posts):
        # All posts rated
        await finish_training_flow(chat_id, message_manager, state)
        return
    
    post = posts[index]
    
    # Get user language for localized texts
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Format post text (fetch from Redis cache or user-bot)
    channel_title = html.escape(post.get("channel_title", "Unknown Channel"))
    channel_username = post.get("channel_username", "").lstrip("@")
    msg_id = post.get("telegram_message_id")
    post_id = post.get("id")
    
    # Get post content from Redis cache first, then user-bot if not cached
    post_text = post.get("text") or ""
    cached_media_type = None
    cached_media_data = None
    
    if post_id:
        post_cache = get_post_cache()
        cached_content = await post_cache.get_post_content(post_id)
        
        if cached_content:
            # Use cached content
            post_text = cached_content.get("text") or ""
            cached_media_type = cached_content.get("media_type")
            cached_media_data = cached_content.get("media_data")  # base64 string
    
    # If not in cache, fetch from user-bot and cache it
    if not post_text and not cached_media_data and channel_username and msg_id:
        user_bot = get_user_bot()
        full_content = await user_bot.get_post_full_content(channel_username, msg_id)
        
        if full_content:
            post_text = full_content.get("text") or ""
            cached_media_type = full_content.get("media_type")
            cached_media_data = full_content.get("media_data")  # base64 string
            
            # Cache the content for future use
            if post_id:
                post_cache = get_post_cache()
                await post_cache.set_post_content(
                    post_id=post_id,
                    text=post_text,
                    media_type=cached_media_type,
                    media_data=cached_media_data
                )
    
    # Prefetch next post content in background
    # If using queue, prefetch next item in queue, otherwise prefetch index + 1
    next_index = None
    if queue and len(queue) > 1:
        next_index = queue[1]  # Second item in queue is next post
    elif not queue and index + 1 < len(posts):
        next_index = index + 1
    
    if next_index is not None and next_index < len(posts):
        next_post = posts[next_index]
        next_post_id = next_post.get("id")
        next_channel_username = next_post.get("channel_username", "").lstrip("@")
        next_msg_id = next_post.get("telegram_message_id")
        
        if next_post_id and next_channel_username and next_msg_id:
            # Check if next post is already cached
            post_cache = get_post_cache()
            next_cached = await post_cache.get_post_content(next_post_id)
            
            if not next_cached:
                # Prefetch next post content in background
                asyncio.create_task(
                    _prefetch_post_content(next_post_id, next_channel_username, next_msg_id)
                )
    
    # Build post text with hyperlink to original (HTML format) - WITHOUT progress counter
    if channel_username and msg_id:
        text = f"📰 {texts.get('from_label', default='From')}: <a href=\"https://t.me/{channel_username}/{msg_id}\">{channel_title}</a>\n\n"
    else:
        text = f"📰 {texts.get('from_label', default='From')}: {channel_title}\n\n"
    text += post_text if post_text else "<i>[Media content]</i>"
    # Telegram counts caption length without HTML tags
    from bot.utils import get_html_text_length
    caption_fits = get_html_text_length(text) <= TELEGRAM_CAPTION_LIMIT
    post_message_id = None

    # Send post as REGULAR message (text/media only, no buttons)
    # Use cached media from Redis if available
    media_type_to_use = cached_media_type or post.get("media_type")
    
    if media_type_to_use == "photo":
        # Try to use cached media data from Redis first
        photo_bytes_from_cache = None
        if cached_media_data:
            try:
                photo_bytes_from_cache = base64.b64decode(cached_media_data.encode('utf-8'))
            except Exception as e:
                logger.warning(f"Failed to decode cached media_data for post {post_id}: {e}")
        
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

        if channel_username and (media_ids or photo_bytes_from_cache):
            user_bot = get_user_bot()
            media_service = _get_media_service()
            cached_photo = await media_service.get_cached_photo(chat_id, post.get("id", 0))
            cached_photos = await media_service.get_cached_photos(chat_id, post.get("id", 0))
            cached = {"photo": cached_photo, "photos": cached_photos} if cached_photo or cached_photos else None
            
            # Prefer Redis cached media over in-memory cache
            if photo_bytes_from_cache:
                cached = {"photo": photo_bytes_from_cache}

            if len(media_ids) > 1:
                # Album
                if cached and cached.get("photos"):
                    photos_data = cached["photos"]
                else:
                    tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    photos_data = [r for r in results if r and not isinstance(r, Exception)]

                media_items: list[InputMediaPhoto] = []
                for i, photo_bytes in enumerate(photos_data):
                    input_file = BufferedInputFile(photo_bytes, filename=f"{media_ids[i] if i < len(media_ids) else i}.jpg")
                    media_items.append(InputMediaPhoto(media=input_file))
                if media_items:
                    msgs = await message_manager.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_items,
                    )
                    # Register all album messages as regular
                    from bot.core.message_registry import ManagedMessage, MessageType
                    for msg in msgs:
                        managed = ManagedMessage(
                            message_id=msg.message_id,
                            chat_id=chat_id,
                            message_type=MessageType.REGULAR,
                            tag="training_post_content"
                        )
                        await message_manager.registry.register(managed)
                    # Use first message of album for reaction
                    post_message_id = msgs[0].message_id if msgs else None
                    # Send text separately as regular message
                    post_msg = await message_manager.send_regular(
                        chat_id=chat_id,
                        text=text,
                        tag="training_post_content",
                    )
                    # Use text message for reaction if available, otherwise first photo
                    if post_msg:
                        post_message_id = post_msg.message_id
                else:
                    # Album failed to load - send text only
                    post_msg = await message_manager.send_regular(
                        chat_id=chat_id,
                        text=text,
                        tag="training_post_content",
                    )
                    if post_msg:
                        post_message_id = post_msg.message_id
            else:
                # Single photo
                mid = media_ids[0]
                if cached and cached.get("photo"):
                    photo_bytes = cached["photo"]
                else:
                    try:
                        photo_bytes = await user_bot.get_photo(channel_username, mid)
                    except Exception:
                        photo_bytes = None
                if photo_bytes:
                    if caption_fits:
                        post_msg = await message_manager.send_regular(
                            chat_id=chat_id,
                            text=text,
                            photo_bytes=photo_bytes,
                            photo_filename=f"{mid}.jpg",
                            tag="training_post_content",
                        )
                        if post_msg:
                            post_message_id = post_msg.message_id
                    else:
                        # Photo without caption, text sent separately
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        msg = await message_manager.bot.send_photo(chat_id=chat_id, photo=input_file)
                        # Register photo as regular
                        from bot.core.message_registry import ManagedMessage, MessageType
                        managed = ManagedMessage(
                            message_id=msg.message_id,
                            chat_id=chat_id,
                            message_type=MessageType.REGULAR,
                            tag="training_post_content"
                        )
                        await message_manager.registry.register(managed)
                        post_msg = await message_manager.send_regular(
                            chat_id=chat_id,
                            text=text,
                            tag="training_post_content",
                        )
                        # Use text message for reaction
                        if post_msg:
                            post_message_id = post_msg.message_id
                else:
                    # Photo failed to load - send text only
                    post_msg = await message_manager.send_regular(
                        chat_id=chat_id,
                        text=text,
                        tag="training_post_content",
                    )
                    if post_msg:
                        post_message_id = post_msg.message_id
        else:
            # No channel_username or media_ids for photo - send text only
            post_msg = await message_manager.send_regular(
                chat_id=chat_id,
                text=text,
                tag="training_post_content",
            )
            if post_msg:
                post_message_id = post_msg.message_id

    elif media_type_to_use == "video" and channel_username and msg_id:
        # Try to use cached media data from Redis first
        video_bytes = None
        if cached_media_data:
            try:
                video_bytes = base64.b64decode(cached_media_data.encode('utf-8'))
            except Exception as e:
                logger.warning(f"Failed to decode cached video media_data for post {post_id}: {e}")
        
        if not video_bytes:
            user_bot = get_user_bot()
            media_service = _get_media_service()
            cached_video = await media_service.get_cached_video(chat_id, post.get("id", 0))
            if cached_video:
                video_bytes = cached_video
            else:
                try:
                    video_bytes = await user_bot.get_video(channel_username, msg_id)
                except Exception:
                    video_bytes = None
        
        if video_bytes:
            try:
                input_file = BufferedInputFile(video_bytes, filename=f"{msg_id}.mp4")
                if caption_fits:
                    msg = await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                    )
                    # Register video message as regular
                    from bot.core.message_registry import ManagedMessage, MessageType
                    managed = ManagedMessage(
                        message_id=msg.message_id,
                        chat_id=chat_id,
                        message_type=MessageType.REGULAR,
                        tag="training_post_content"
                    )
                    await message_manager.registry.register(managed)
                    post_message_id = msg.message_id
                else:
                    msg = await message_manager.bot.send_video(chat_id=chat_id, video=input_file)
                    # Register video as regular
                    from bot.core.message_registry import ManagedMessage, MessageType
                    managed = ManagedMessage(
                        message_id=msg.message_id,
                        chat_id=chat_id,
                        message_type=MessageType.REGULAR,
                        tag="training_post_content"
                    )
                    await message_manager.registry.register(managed)
                    post_msg = await message_manager.send_regular(
                        chat_id=chat_id,
                        text=text,
                        tag="training_post_content",
                    )
                    # Use text message for reaction
                    if post_msg:
                        post_message_id = post_msg.message_id
            except Exception as e:
                logger.warning(f"Failed to send video for post {post.get('id')}: {e}")
                new_index = index + 1
                await state.update_data(current_post_index=new_index)
                await show_training_post(chat_id, message_manager, state)
                return
        else:
            # Video failed to download - send text only
            logger.warning(f"Failed to download video for post {post.get('id')}, sending text only")
            post_msg = await message_manager.send_regular(
                chat_id=chat_id,
                text=text,
                tag="training_post_content",
            )
            if post_msg:
                post_message_id = post_msg.message_id

    # Send text-only post as regular message if not already sent
    if post_message_id is None:
        post_msg = await message_manager.send_regular(
            chat_id=chat_id,
            text=text,
            tag="training_post_content",
        )
        if post_msg:
            post_message_id = post_msg.message_id
    
    # Now send temporary message with progress and buttons
    # Use initial_queue_size for total (saved at start, doesn't change)
    rated_count = data.get("rated_count", 0)
    initial_queue_size = data.get("initial_queue_size", len(queue) if queue else len(posts))
    progress_text = texts.get("training_progress", current=rated_count, total=initial_queue_size)
    await message_manager.send_temporary(
        chat_id,
        progress_text,
        reply_markup=get_training_post_keyboard(post.get("id"), lang),
        tag="training_post_controls",
    )
    
    # Save post message ID for reaction
    await state.update_data(
        current_post_message_id=post_message_id,
    )
    
    # Start background prefetch for next posts
    media_service = _get_media_service()
    asyncio.create_task(
        media_service.prefetch_posts_media(chat_id, posts, index + 1, count=3)
    )


async def finish_training_flow(chat_id: int, message_manager: MessageManager, state: FSMContext):
    """Complete training and update user status."""
    logger.info(f"finish_training_flow called for chat_id={chat_id}")
    api = get_core_api()
    data = await state.get_data()
    
    # Clear training posts from state
    training_posts = data.get("training_posts", [])
    rated_count = data.get("rated_count", 0)
    user_id = data.get("user_id")
    is_bonus_training = bool(data.get("is_bonus_training"))
    is_retrain = bool(data.get("is_retrain"))
    
    # Reset user status from "training" to "active"
    # Role will be updated to MEMBER automatically in mark_training_complete
    if user_id:
        await api.update_user(user_id, status="active")
    
    # Clean up all training-related messages
    await message_manager.delete_temporary(chat_id, tag="training_post_controls")
    await message_manager.delete_temporary(chat_id, tag="bonus_nudge")
    await message_manager.delete_temporary(chat_id, tag="miniapp_choice")
    
    # Clear media cache for this chat to prevent late posts
    media_service = _get_media_service()
    await media_service.clear_cache(chat_id)

    # Get user language
    lang = await _get_user_lang(user_id) if user_id else "en_US"
    texts = get_texts(lang)

    user_has_bonus = False
    if user_id is not None:
        user_data = await api.get_user(user_id)
        if user_data:
            user_has_bonus = user_data.get("bonus_channels_count", 0) >= 1

        # запустить нуджи по бонус-каналу
        try:
            asyncio.create_task(
                _bonus_channel_nudge_watcher(chat_id, user_id, message_manager)
            )
        except Exception as e:
            logger.error(f"Error starting bonus nudge watcher for user {user_id}: {e}")

        # Send one best post from M−N (posts not shown in training) after a short delay
        exclude_post_ids = [p.get("id") for p in training_posts if p.get("id") is not None]
        async def delayed_best_post():
            await asyncio.sleep(60)  # Wait 1 minute
            try:
                await send_initial_best_post(chat_id, user_id, message_manager, exclude_post_ids)
            except Exception as e:
                logger.error(f"Error sending best post after training for user {user_id}: {e}")
        
        asyncio.create_task(delayed_best_post())

    await state.clear()

    # По плану: после тренировки вызывается системно стартовое сообщение для зарегистрированного
    name = "there"
    if user_id:
        user_data = await api.get_user(user_id)
        if user_data and user_data.get("first_name"):
            name = user_data["first_name"]
    name = html.escape(name)
    channels = await api.get_user_channels_with_meta(user_id) if user_id else []
    mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
    await message_manager.send_system(
        chat_id,
        texts.get("welcome_back", name=name),
        reply_markup=get_feed_keyboard(lang, has_bonus_channel=user_has_bonus, mailing_any_on=mailing_any_on),
        tag="menu",
    )
    logger.info(f"finish_training_flow completed for chat_id={chat_id}")


async def send_initial_best_post(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
    exclude_post_ids: Optional[List[int]] = None,
) -> None:
    """Send one best post from M−N (posts not shown in training) after training.

    Uses get_best_posts with exclude_post_ids so we only send a post that was not
    in the training queue. If M−N is 0 or no candidate, nothing is sent.
    """
    from aiogram.types import InputMediaPhoto, BufferedInputFile, LinkPreviewOptions
    from bot.core import get_feed_post_keyboard
    
    api = get_core_api()
    user_bot = get_user_bot()

    await api.update_activity(user_id)
    user_data = await api.get_user(user_id)
    if not user_data:
        return

    if user_data.get("status") == "training":
        return

    result = await api.train_model(user_id)
    if not result or not result.get("success"):
        logger.warning(
            "ML training after initial training failed for user %s: %s",
            user_id,
            (result or {}).get("message"),
        )

    all_posts = await api.get_best_posts(user_id, limit=1, exclude_post_ids=exclude_post_ids or [])
    if not all_posts:
        return

    initial_best_post = all_posts[0]

    # Send this post similarly to feed posts (with rating buttons)
    channel_title = html.escape(initial_best_post.get("channel_title", "Unknown"))
    channel_username = (initial_best_post.get("channel_username") or "").lstrip("@")
    msg_id = initial_best_post.get("telegram_message_id")
    
    # Get post text - fetch from user-bot if not available
    full_text_raw = initial_best_post.get("text") or ""
    if not full_text_raw and channel_username and msg_id:
        full_text_raw = await user_bot.get_post_text(channel_username, msg_id) or ""
    text = full_text_raw  # Already HTML formatted from user-bot
    score = initial_best_post.get("relevance_score", 0)

    # Build header with link to original post (HTML format)
    if channel_username and msg_id:
        header = f"📰 <a href=\"https://t.me/{channel_username}/{msg_id}\">{channel_title}</a>\n\n"
    else:
        header = f"📰 <b>{channel_title}</b>\n\n"
    body = text if text else "<i>[Media content]</i>"
    post_text = header + body

    # Telegram counts caption length without HTML tags
    from bot.utils import get_html_text_length
    caption_fits = get_html_text_length(post_text) <= TELEGRAM_CAPTION_LIMIT
    sent_with_caption = False

    if initial_best_post.get("media_type") == "photo":
        channel_username = initial_best_post.get("channel_username")
        media_ids_str = initial_best_post.get("media_file_id") or ""

        media_ids: list[int] = []
        if media_ids_str:
            for part in media_ids_str.split(","):
                part = part.strip()
                if part.isdigit():
                    media_ids.append(int(part))
        else:
            msg_id = initial_best_post.get("telegram_message_id")
            if isinstance(msg_id, int):
                media_ids.append(msg_id)

        if channel_username and media_ids:
            if len(media_ids) > 1:
                # Download all photos in parallel
                tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                media_items: list[InputMediaPhoto] = []
                for mid, photo_bytes in zip(media_ids, results):
                    if isinstance(photo_bytes, Exception) or not photo_bytes:
                        continue
                    input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                    media_items.append(InputMediaPhoto(media=input_file))
                if media_items:
                    await message_manager.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_items,
                    )
                    # Send text separately (no buttons)
                    await message_manager.bot.send_message(
                        chat_id=chat_id,
                        text=post_text,
                        parse_mode="HTML",
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
                    # Send buttons separately
                    if initial_best_post.get("id"):
                        await message_manager.send_temporary(
                            chat_id,
                            "👆",
                            reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                            tag="feed_post_buttons",
                        )
                    sent_with_caption = True
            else:
                mid = media_ids[0]
                try:
                    photo_bytes = await user_bot.get_photo(channel_username, mid)
                except Exception:
                    photo_bytes = None
                if photo_bytes:
                    if caption_fits:
                        # Photo + caption together (no buttons)
                        await message_manager.send_regular(
                            chat_id,
                            post_text,
                            tag="feed_post",
                            photo_bytes=photo_bytes,
                            photo_filename=f"{mid}.jpg",
                        )
                        # Buttons separately
                        if initial_best_post.get("id"):
                            await message_manager.send_temporary(
                                chat_id,
                                "👆",
                                reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                                tag="feed_post_buttons",
                            )
                        sent_with_caption = True
                    else:
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        await message_manager.bot.send_photo(
                            chat_id=chat_id,
                            photo=input_file,
                        )

    # Handle video posts
    if initial_best_post.get("media_type") == "video" and not sent_with_caption:
        channel_username = initial_best_post.get("channel_username")
        msg_id = initial_best_post.get("telegram_message_id")
        if channel_username and msg_id:
            try:
                video_bytes = await user_bot.get_video(channel_username, msg_id)
            except Exception:
                video_bytes = None
            if video_bytes:
                input_file = BufferedInputFile(video_bytes, filename=f"{msg_id}.mp4")
                if caption_fits:
                    # Video + caption together (no buttons)
                    await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                        caption=post_text,
                        parse_mode=ParseMode.HTML,
                    )
                    # Buttons separately
                    if initial_best_post.get("id"):
                        await message_manager.send_temporary(
                            chat_id,
                            "👆",
                            reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                            tag="feed_post_buttons",
                        )
                    sent_with_caption = True
                else:
                    await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                    )

    if not sent_with_caption:
        # Text only (no buttons)
        await message_manager.bot.send_message(
            chat_id=chat_id,
            text=post_text,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        # Buttons separately
        if initial_best_post.get("id"):
            await message_manager.send_temporary(
                chat_id,
                "👆",
                reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                tag="feed_post_buttons",
            )


