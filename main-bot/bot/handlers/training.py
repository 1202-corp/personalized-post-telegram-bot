"""Training flow handlers (onboarding, rating posts, etc.)."""

import json
import logging
import asyncio
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.message_manager import MessageManager
from bot.api_client import get_core_api, get_user_bot
from bot.utils import escape_md, send_post_with_media, TELEGRAM_CAPTION_LIMIT
from bot.keyboards import (
    get_start_keyboard, get_onboarding_keyboard, get_add_channel_keyboard,
    get_training_post_keyboard, get_miniapp_keyboard, get_training_complete_keyboard,
    get_cancel_keyboard, get_feed_keyboard, get_feed_post_keyboard, get_retrain_keyboard,
)
from bot.texts import TEXTS, get_texts
from bot.config import get_settings

logger = logging.getLogger(__name__)
router = Router()
settings = get_settings()

# Track processed callbacks to prevent double-click
_processed_rate_callbacks: set = set()

# Media prefetch cache: {(chat_id, post_id): {"photo": bytes, "video": bytes}}
_media_cache: dict = {}
_prefetch_tasks: dict = {}  # Track running prefetch tasks


async def _prefetch_single_post(chat_id: int, post: dict) -> None:
    """Prefetch media for a single post."""
    user_bot = get_user_bot()
    post_id = post.get("id")
    cache_key = (chat_id, post_id)
    
    if cache_key in _media_cache:
        return
    
    media_type = post.get("media_type")
    channel_username = post.get("channel_username", "").lstrip("@")
    
    if not channel_username:
        return
    
    try:
        if media_type == "photo":
            media_ids_str = post.get("media_file_id") or ""
            media_ids = []
            if media_ids_str:
                for part in media_ids_str.split(","):
                    part = part.strip()
                    if part.isdigit():
                        media_ids.append(int(part))
            
            if media_ids:
                # Parallel download all photos in album
                tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids[:5]]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                photos = [r for r in results if r and not isinstance(r, Exception)]
                if photos:
                    _media_cache[cache_key] = {"photo": photos[0], "photos": photos}
        
        elif media_type == "video":
            msg_id = post.get("telegram_message_id")
            if msg_id:
                video_bytes = await user_bot.get_video(channel_username, msg_id)
                if video_bytes:
                    _media_cache[cache_key] = {"video": video_bytes}
    except Exception as e:
        logger.debug(f"Prefetch failed for post {post_id}: {e}")


async def _prefetch_media_for_posts(
    chat_id: int,
    posts: list,
    start_index: int,
    count: int = 5
) -> None:
    """Prefetch media for upcoming posts in PARALLEL."""
    posts_to_prefetch = posts[start_index:start_index + count]
    
    # Run all prefetches in parallel
    tasks = [_prefetch_single_post(chat_id, post) for post in posts_to_prefetch]
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # Cleanup old cache entries (keep last 30)
    if len(_media_cache) > 30:
        keys = list(_media_cache.keys())
        for k in keys[:-30]:
            _media_cache.pop(k, None)


async def _prefetch_all_training_posts(chat_id: int, posts: list) -> None:
    """Prefetch ALL training posts in parallel batches."""
    batch_size = 5
    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        tasks = [_prefetch_single_post(chat_id, post) for post in batch]
        await asyncio.gather(*tasks, return_exceptions=True)
        # Small delay between batches to not overwhelm
        await asyncio.sleep(0.1)


async def _get_user_lang(user_id: int) -> str:
    """Get user's language preference."""
    api = get_core_api()
    return await api.get_user_language(user_id)


class TrainingStates(StatesGroup):
    """FSM states for training flow."""
    waiting_for_channel = State()
    rating_posts = State()

# Note: on_open_miniapp handler removed - MiniApp now opens directly via WebAppInfo in keyboard


@router.message(F.web_app_data)
async def on_web_app_data(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Handle data sent from MiniApp via tg.sendData().
    
    Expected data format:
    {
        "action": "training_complete",
        "rated_count": 15,
        "user_id": 123456789
    }
    """
    try:
        data = json.loads(message.web_app_data.data)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON from web_app_data: {message.web_app_data.data}")
        return
    
    action = data.get("action")
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    logger.info(f"Received web_app_data from user {user_id}: action={action}")
    
    api = get_core_api()
    await api.update_activity(user_id)
    
    if action == "training_complete":
        rated_count = data.get("rated_count", 0)
        
        # Log training completion
        await api.create_log(user_id, "miniapp_training_complete", f"rated_count={rated_count}")
        
        # Get existing state to preserve is_bonus_training and is_retrain flags
        existing_state = await state.get_data()
        is_bonus_training = existing_state.get("is_bonus_training", False)
        is_retrain = existing_state.get("is_retrain", False)
        
        # Update user state (preserve bonus/retrain flags)
        await state.update_data(
            rated_count=rated_count,
            user_id=user_id,
            is_bonus_training=is_bonus_training,
            is_retrain=is_retrain,
        )
        
        # Complete training flow
        await finish_training_flow(chat_id, message_manager, state)
    
    elif action == "interaction":
        # Handle individual post interactions from MiniApp
        post_id = data.get("post_id")
        interaction_type = data.get("type")  # like, dislike, skip
        
        if post_id and interaction_type and interaction_type != "skip":
            await api.create_interaction(user_id, post_id, interaction_type)
            await api.create_log(user_id, f"miniapp_post_{interaction_type}", f"post_id={post_id}")
    
    else:
        logger.warning(f"Unknown web_app_data action: {action}")


@router.callback_query(F.data == "start_training")
async def on_start_training(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Handle Start Training button - scrape posts and show MiniApp/chat choice."""
    await callback.answer()
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = callback.from_user.id
    await api.update_activity(user_id)
    await api.create_log(user_id, "start_training_clicked")
    
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Show loading message
    try:
        await callback.message.edit_text(texts.get("fetching_posts"))
    except Exception:
        pass
    
    # Scrape posts for training (same as before showing choice)
    default_channels = settings.default_training_channels.split(",")
    channels_to_scrape = [ch.strip() for ch in default_channels]
    
    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        if ch.get("username"):
            channels_to_scrape.append(f"@{ch['username']}")
    
    # Trigger scraping
    scrape_tasks = []
    for channel in channels_to_scrape[:3]:
        task = user_bot.scrape_channel(channel, limit=settings.posts_per_channel)
        scrape_tasks.append(task)
    
    await asyncio.gather(*scrape_tasks, return_exceptions=True)
    
    # Show training choice with MiniApp as main action
    try:
        await callback.message.edit_text(
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang, user_id, channels_to_scrape[:3]),
        )
    except Exception:
        pass


async def _start_training_session(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
    state: FSMContext,
) -> None:
    """Initialize per-session nudge watcher and show the first training post."""
    # Bump session id to invalidate previous watchers
    session_id = f"{user_id}-{int(datetime.utcnow().timestamp() * 1000)}"
    await state.update_data(
        nudge_session_id=session_id,
    )

    # Start nudge watcher
    asyncio.create_task(
        _training_nudge_watcher(chat_id, user_id, message_manager, state, session_id)
    )
    
    # Start background prefetch of ALL posts while showing first one
    data = await state.get_data()
    posts = data.get("training_posts", [])
    if posts:
        asyncio.create_task(_prefetch_all_training_posts(chat_id, posts))

    await show_training_post(chat_id, message_manager, state)


async def _training_nudge_watcher(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
    state: FSMContext,
    session_id: str,
) -> None:
    """Background watcher that sends inactivity nudges during training.

    Sends up to three nudges:
    - after ~1 minute of inactivity
    - after ~1 hour of inactivity
    - after ~2 days of inactivity
    """
    try:
        thresholds = [60, 3600, 2 * 24 * 3600]  # seconds

        while True:
            # Stop if state changed or session was reset
            state_name = await state.get_state()
            data = await state.get_data()
            if data.get("nudge_session_id") != session_id:
                break
            if state_name != TrainingStates.rating_posts:
                break

            last_ts = data.get("last_activity_ts")
            nudge_stage = int(data.get("nudge_stage", 0) or 0)

            if last_ts is None or nudge_stage >= len(thresholds):
                await asyncio.sleep(10)
                continue

            now_ts = datetime.utcnow().timestamp()
            delta = now_ts - float(last_ts)

            if delta >= thresholds[nudge_stage]:
                # Send corresponding nudge message
                lang = await _get_user_lang(user_id)
                texts = get_texts(lang)
                key = f"training_nudge_{nudge_stage + 1}"
                text = texts.get(key)
                if not text:
                    # Fallback generic text if localization key is missing
                    text = "⏰ Training is still in progress. Rate a few more posts so I can personalize your feed."

                await message_manager.send_ephemeral(
                    chat_id,
                    text,
                    tag="training_nudge",
                )

                nudge_stage += 1
                await state.update_data(nudge_stage=nudge_stage)

            await asyncio.sleep(10)
    except Exception as e:
        logger.error(f"Error in training nudge watcher for user {user_id}: {e}")

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

            from bot.keyboards import get_bonus_channel_keyboard

            await message_manager.send_ephemeral(
                chat_id,
                text,
                reply_markup=get_bonus_channel_keyboard(lang),
                tag="bonus_nudge",
            )
        except Exception as e:
            logger.error(f"Error in bonus channel nudge watcher for user {user_id}: {e}")
            break


@router.callback_query(F.data == "how_it_works")
async def on_how_it_works(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show how the bot works."""
    await callback.answer()
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    await message_manager.send_ephemeral(
        callback.message.chat.id,
        texts.get("how_it_works"),
        auto_delete_after=20.0
    )


@router.callback_query(F.data == "confirm_training")
async def on_confirm_training(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Start the actual training process."""
    await callback.answer("🚀 Starting training...")
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = callback.from_user.id
    
    await api.update_activity(user_id)
    await api.update_user(user_id, status="training")
    await api.create_log(user_id, "training_started")
    
    # Show loading message
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("fetching_posts"),
        tag="menu"
    )
    
    # Get training channels (defaults + user-added)
    default_channels = settings.default_training_channels.split(",")
    channels_to_scrape = [ch.strip() for ch in default_channels]
    
    # Get user's custom channels if any
    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        if ch.get("username"):
            channels_to_scrape.append(f"@{ch['username']}")
    
    # Trigger scraping for each channel
    scrape_tasks = []
    for channel in channels_to_scrape[:3]:  # Limit to 3 channels
        task = user_bot.scrape_channel(channel, limit=settings.posts_per_channel)
        scrape_tasks.append(task)
    
    # Wait for all scraping to complete
    await asyncio.gather(*scrape_tasks, return_exceptions=True)
    
    # Get training posts from database
    posts = await api.get_training_posts(
        user_id,
        channels_to_scrape[:3],
        settings.posts_per_channel
    )
    
    if not posts:
        lang = await _get_user_lang(user_id)
        texts = get_texts(lang)
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("no_posts_training"),
            reply_markup=get_onboarding_keyboard(lang),
            tag="menu"
        )
        return
    
    # Store posts in state for rating
    await state.update_data(
        user_id=user_id,
        training_posts=posts,
        current_post_index=0,
        rated_count=0,
        last_media_ids=[],
        last_activity_ts=datetime.utcnow().timestamp(),
        nudge_stage=0,
    )
    await state.set_state(TrainingStates.rating_posts)

    # Start inactivity nudge watcher and show first post
    await _start_training_session(callback.message.chat.id, callback.from_user.id, message_manager, state)


async def show_training_post(chat_id: int, message_manager: MessageManager, state: FSMContext):
    """Display current training post for rating."""
    data = await state.get_data()
    posts = data.get("training_posts", [])
    index = data.get("current_post_index", 0)
    user_id = data.get("user_id")
    
    if index >= len(posts):
        # All posts rated
        await finish_training_flow(chat_id, message_manager, state)
        return
    
    post = posts[index]
    is_last = (index == len(posts) - 1)
    
    # Format post text (escape user content for Markdown)
    channel_title = escape_md(post.get("channel_title", "Unknown Channel"))
    full_text_raw = post.get("text") or ""
    post_text = escape_md(full_text_raw)
    channel_username = post.get("channel_username", "").lstrip("@")
    msg_id = post.get("telegram_message_id")
    
    # Get user language for localized texts
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Build post text with hyperlink to original
    text = f"📰 *{texts.get('post_label', default='Post')} {index + 1}/{len(posts)}*\n"
    if channel_username and msg_id:
        text += f"{texts.get('from_label', default='From')}: [{escape_md(channel_title)}](https://t.me/{channel_username}/{msg_id})\n\n"
    else:
        text += f"{texts.get('from_label', default='From')}: {escape_md(channel_title)}\n\n"
    text += post_text if post_text else "_[Media content]_"
    caption_fits = len(text) <= TELEGRAM_CAPTION_LIMIT
    sent_with_caption = False
    media_message_ids: list[int] = []

    # First send media if available (photo or video)
    media_type = post.get("media_type")
    if media_type == "photo":
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
            from aiogram.types import InputMediaPhoto, BufferedInputFile
            
            # Check cache first for ALL photo types
            cache_key = (chat_id, post.get("id"))
            cached = _media_cache.pop(cache_key, None)

            if len(media_ids) > 1:
                # Album - check cache or download in parallel
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
                    media_message_ids.extend(m.message_id for m in msgs)
            else:
                # Single photo - use cache or download
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
                        await message_manager.delete_ephemeral(chat_id, tag="training_post")
                        await message_manager.send_ephemeral(
                            chat_id,
                            text,
                            reply_markup=get_training_post_keyboard(post.get("id"), lang),
                            tag="training_post",
                            photo_bytes=photo_bytes,
                            photo_filename=f"{mid}.jpg",
                        )
                        sent_with_caption = True
                    else:
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        msg = await message_manager.bot.send_photo(
                            chat_id=chat_id,
                            photo=input_file,
                        )
                        media_message_ids.append(msg.message_id)

    elif media_type == "video" and channel_username and msg_id:
        # Handle video posts - skip if video fails to load/send
        user_bot = get_user_bot()
        from aiogram.types import BufferedInputFile
        # Check cache first
        cache_key = (chat_id, post.get("id"))
        cached = _media_cache.pop(cache_key, None)
        if cached and cached.get("video"):
            video_bytes = cached["video"]
        else:
            try:
                video_bytes = await user_bot.get_video(channel_username, msg_id)
            except Exception:
                video_bytes = None
        
        if video_bytes:
            try:
                input_file = BufferedInputFile(video_bytes, filename=f"{msg_id}.mp4")
                if caption_fits:
                    await message_manager.delete_ephemeral(chat_id, tag="training_post")
                    msg = await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                        caption=text,
                        parse_mode="Markdown",
                        reply_markup=get_training_post_keyboard(post.get("id"), lang),
                    )
                    sent_with_caption = True
                else:
                    msg = await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                    )
                    media_message_ids.append(msg.message_id)
            except Exception as e:
                # Video send failed (timeout, too large, etc.) - skip to next post
                logger.warning(f"Failed to send video for post {post.get('id')}: {e}")
                new_index = index + 1
                await state.update_data(current_post_index=new_index)
                await show_training_post(chat_id, message_manager, state)
                return
        else:
            # Video failed to download - skip to next post
            logger.warning(f"Failed to download video for post {post.get('id')}, skipping")
            new_index = index + 1
            await state.update_data(current_post_index=new_index)
            await show_training_post(chat_id, message_manager, state)
            return

    # Send text-only ephemeral (will be replaced by next post) when not already sent as caption
    if not sent_with_caption:
        await message_manager.delete_ephemeral(chat_id, tag="training_post")
        await message_manager.send_ephemeral(
            chat_id,
            text,
            reply_markup=get_training_post_keyboard(post.get("id"), lang),
            tag="training_post",
            disable_link_preview=True,
        )
    
    # Remember media messages for later cleanup on rating
    await state.update_data(last_media_ids=media_message_ids)
    
    # Update system message with progress
    total = len(posts)
    progress_text = texts.get("training_progress", current=index, total=total)

    await message_manager.send_system(
        chat_id,
        progress_text,
        tag="menu",
    )
    
    # Update activity timestamp AFTER message is sent (for accurate nudge timing)
    await state.update_data(last_activity_ts=datetime.utcnow().timestamp())
    
    # Start background prefetch for next posts
    asyncio.create_task(_prefetch_media_for_posts(chat_id, posts, index + 1, count=3))


@router.callback_query(F.data.startswith("rate:"))
async def on_rate_post(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle post rating (like/dislike/skip)."""
    # Prevent double-click
    callback_key = f"{callback.from_user.id}:{callback.message.message_id}"
    if callback_key in _processed_rate_callbacks:
        await callback.answer()
        return
    _processed_rate_callbacks.add(callback_key)
    
    # Clean up old entries (keep only last 100)
    if len(_processed_rate_callbacks) > 100:
        _processed_rate_callbacks.clear()
    
    _, action, post_id = callback.data.split(":")
    post_id = int(post_id)
    
    await callback.answer(f"{'👍' if action == 'like' else '👎' if action == 'dislike' else '⏭️'}")
    
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.update_activity(user_id)
    
    # Record interaction (skip action == 'skip')
    if action != "skip":
        await api.create_interaction(user_id, post_id, action)
        await api.create_log(user_id, f"post_{action}", f"post_id={post_id}")

    # Any rating counts as activity: clear nudges and update last activity
    await message_manager.delete_ephemeral(callback.message.chat.id, tag="training_nudge")

    # Clean up media and text for the rated post
    data = await state.get_data()
    last_media_ids = data.get("last_media_ids", []) or []
    for mid in last_media_ids:
        try:
            await message_manager.bot.delete_message(callback.message.chat.id, mid)
        except Exception:
            pass
    await message_manager.delete_ephemeral(callback.message.chat.id, tag="training_post")
    
    # Move to next post
    new_index = data.get("current_post_index", 0) + 1
    rated_count = data.get("rated_count", 0) + (1 if action != "skip" else 0)
    
    await state.update_data(
        current_post_index=new_index,
        rated_count=rated_count,
        last_media_ids=[],
        last_activity_ts=datetime.utcnow().timestamp(),
    )
    
    # Show next post
    await show_training_post(callback.message.chat.id, message_manager, state)


@router.callback_query(F.data == "finish_training")
async def on_finish_training(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Finish training and trigger ML model."""
    await callback.answer("🎯 Finishing training...")
    # Clear any pending training nudges
    await message_manager.delete_ephemeral(callback.message.chat.id, tag="training_nudge")
    await finish_training_flow(callback.message.chat.id, message_manager, state)


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
    if user_id:
        await api.update_user(user_id, status="active", is_trained=True)
    
    # Clean up all training-related messages
    await message_manager.delete_ephemeral(chat_id, tag="training_post")
    await message_manager.delete_ephemeral(chat_id, tag="training_nudge")
    await message_manager.delete_ephemeral(chat_id, tag="bonus_nudge")
    await message_manager.delete_ephemeral(chat_id, tag="miniapp_choice")
    
    # Clear media cache for this chat to prevent late posts
    keys_to_remove = [k for k in _media_cache.keys() if k[0] == chat_id]
    for k in keys_to_remove:
        _media_cache.pop(k, None)

    # Get user language
    lang = await _get_user_lang(user_id) if user_id else "en"
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

        # отправить один лучший пост через минуту после обучения
        async def delayed_best_post():
            await asyncio.sleep(60)  # Wait 1 minute
            try:
                await send_initial_best_post(chat_id, user_id, message_manager)
            except Exception as e:
                logger.error(f"Error sending initial best post after training for user {user_id}: {e}")
        
        asyncio.create_task(delayed_best_post())

    await state.clear()

    if is_retrain or is_bonus_training or user_has_bonus:
        # After retraining, bonus training, or if bonus already claimed – go straight to feed
        logger.info(f"Sending feed_ready to chat_id={chat_id} (is_retrain={is_retrain}, is_bonus={is_bonus_training})")
        await message_manager.send_system(
            chat_id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=user_has_bonus),
            tag="menu",
        )
    else:
        logger.info(f"Sending training_complete to chat_id={chat_id}, rated_count={rated_count}")
        await message_manager.send_system(
            chat_id,
            texts.get("training_complete", rated_count=rated_count),
            reply_markup=get_training_complete_keyboard(lang),
            tag="menu",
        )
    logger.info(f"finish_training_flow completed for chat_id={chat_id}")



async def send_initial_best_post(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
) -> None:
    """Train ML model and send a single best recent post once after training.

    Uses the same best-post logic as the feed, but triggers immediately after training
    to show the user value without requiring extra button presses.
    """
    api = get_core_api()
    user_bot = get_user_bot()

    await api.update_activity(user_id)
    user_data = await api.get_user(user_id)
    if not user_data:
        return

    # Don't send posts if user is in training mode
    if user_data.get("status") == "training":
        return

    if user_data.get("initial_best_post_sent", False):
        # Already sent once, do not spam
        return

    # Train ML model (mock) so relevance scores are available
    result = await api.train_model(user_id)
    if not result or not result.get("success"):
        logger.warning(
            "ML training after initial training failed for user %s: %s",
            user_id,
            (result or {}).get("message"),
        )

    all_posts = await api.get_best_posts(user_id, limit=10)
    if not all_posts:
        return

    now = datetime.utcnow()
    three_days_ago = now - timedelta(days=3)

    initial_best_post = None
    for post in all_posts:
        posted_at_raw = post.get("posted_at")
        try:
            posted_at = datetime.fromisoformat(posted_at_raw) if posted_at_raw else None
        except Exception:
            posted_at = None
        if posted_at and posted_at >= three_days_ago:
            initial_best_post = post
            break

    if not initial_best_post:
        initial_best_post = all_posts[0]

    # Send this post similarly to feed posts (with rating buttons)
    channel_title = escape_md(initial_best_post.get("channel_title", "Unknown"))
    channel_username = (initial_best_post.get("channel_username") or "").lstrip("@")
    msg_id = initial_best_post.get("telegram_message_id")
    full_text_raw = initial_best_post.get("text") or ""
    text = escape_md(full_text_raw)
    score = initial_best_post.get("relevance_score", 0)

    # Build header with link to original post
    if channel_username and msg_id:
        header = f"📰 [{channel_title}](https://t.me/{channel_username}/{msg_id})\n\n"
    else:
        header = f"📰 *{channel_title}*\n\n"
    body = text if text else "_[Media content]_"
    post_text = header + body

    caption_fits = len(post_text) <= TELEGRAM_CAPTION_LIMIT
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
            from aiogram.types import InputMediaPhoto, BufferedInputFile

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
            else:
                mid = media_ids[0]
                try:
                    photo_bytes = await user_bot.get_photo(channel_username, mid)
                except Exception:
                    photo_bytes = None
                if photo_bytes:
                    from aiogram.types import BufferedInputFile
                    if caption_fits:
                        await message_manager.send_onetime(
                            chat_id,
                            post_text,
                            reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                            tag="feed_post",
                            photo_bytes=photo_bytes,
                            photo_filename=f"{mid}.jpg",
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
                from aiogram.types import BufferedInputFile
                input_file = BufferedInputFile(video_bytes, filename=f"{msg_id}.mp4")
                if caption_fits:
                    await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                        caption=post_text,
                        parse_mode="Markdown",
                        reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                    )
                    sent_with_caption = True
                else:
                    await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                    )

    if not sent_with_caption:
        from aiogram.types import LinkPreviewOptions
        await message_manager.bot.send_message(
            chat_id=chat_id,
            text=post_text,
            parse_mode="Markdown",
            reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    # Mark as sent so we don't send again
    await api.update_user(user_id, initial_best_post_sent=True)


async def start_full_retrain(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start a new full retraining session using user's current channels.

    This is used by the Settings -> Retrain button to let the user re-rate posts
    without wiping their data. Shows MiniApp/chat choice.
    """
    api = get_core_api()
    user_bot = get_user_bot()

    await api.update_activity(user_id)
    # Set status to training to prevent feed posts during retrain
    await api.update_user(user_id, status="training")

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    # Show loading message
    await message_manager.send_system(
        chat_id,
        texts.get("fetching_posts"),
        tag="menu",
    )

    # Collect channels: default ones + user's own
    default_channels = settings.default_training_channels.split(",")
    channels_to_scrape = [ch.strip() for ch in default_channels]

    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        if ch.get("username"):
            channels_to_scrape.append(f"@{ch['username']}")

    scrape_tasks = []
    for channel in channels_to_scrape[:3]:
        scrape_tasks.append(user_bot.scrape_channel(channel, limit=settings.posts_per_channel))

    await asyncio.gather(*scrape_tasks, return_exceptions=True)

    # Store retrain info in state
    await state.update_data(
        user_id=user_id,
        is_retrain=True,
    )

    # Use retrain keyboard with back button
    await message_manager.send_system(
        chat_id,
        texts.get("retrain_intro", default="🔄 Переобучение модели"),
        reply_markup=get_retrain_keyboard(lang, user_id, channels_to_scrape[:3]),
        tag="menu",
    )


async def start_bonus_training(
    chat_id: int,
    user_id: int,
    username: str,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start an additional short training flow focused on a bonus channel.
    
    Shows MiniApp/chat choice, scrapes channel first so posts are ready.
    """
    api = get_core_api()
    user_bot = get_user_bot()

    await api.update_activity(user_id)
    await api.create_log(user_id, "bonus_training_started", username)
    await api.update_user(user_id, status="training")

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    # Show loading
    await message_manager.send_system(
        chat_id,
        texts.get("fetching_posts"),
        tag="menu",
    )

    # Scrape the bonus channel
    try:
        await user_bot.scrape_channel(username, limit=settings.posts_per_channel)
    except Exception:
        pass

    # Store bonus channel info in state for later use
    await state.update_data(
        bonus_channel_username=username,
        is_bonus_training=True,
    )

    # Show MiniApp choice (same as regular training)
    url = f"{settings.miniapp_url}?user_id={user_id}&channel={username.lstrip('@')}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get("miniapp_btn_open"), web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton(text=texts.get("miniapp_btn_rate_in_chat"), callback_data=f"confirm_bonus_training:{username}")],
    ])

    await message_manager.send_system(
        chat_id,
        texts.get("bonus_training_intro", username=username),
        reply_markup=keyboard,
        tag="menu",
    )


@router.callback_query(F.data.startswith("confirm_bonus_training:"))
async def on_confirm_bonus_training(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start bonus training in chat mode."""
    await callback.answer()
    username = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    api = get_core_api()

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    channels_to_scrape = [username]

    # Get training posts only from this bonus channel
    posts = await api.get_training_posts(
        user_id,
        channels_to_scrape,
        settings.posts_per_channel,
    )

    if not posts:
        await state.clear()
        # User tried to add bonus but no posts found, they still don't have bonus
        await message_manager.send_system(
            chat_id,
            texts.get("bonus_training_no_posts", username=username),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=False),
            tag="menu",
        )
        return

    await state.update_data(
        user_id=user_id,
        training_posts=posts,
        current_post_index=0,
        rated_count=0,
        last_media_ids=[],
        last_activity_ts=datetime.utcnow().timestamp(),
        nudge_stage=0,
        is_bonus_training=True,
    )
    await state.set_state(TrainingStates.rating_posts)

    await _start_training_session(chat_id, user_id, message_manager, state)


@router.callback_query(F.data == "confirm_retrain")
async def on_confirm_retrain(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start retraining in chat mode."""
    await callback.answer()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    api = get_core_api()
    user_bot = get_user_bot()

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    # Collect channels: default ones + user's own
    default_channels = settings.default_training_channels.split(",")
    channels_to_scrape = [ch.strip() for ch in default_channels]

    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        if ch.get("username"):
            channels_to_scrape.append(f"@{ch['username']}")

    posts = await api.get_training_posts(
        user_id,
        channels_to_scrape[:3],
        settings.posts_per_channel,
    )

    if not posts:
        await state.clear()
        await message_manager.send_ephemeral(
            chat_id,
            texts.get("no_posts_training"),
            auto_delete_after=5.0,
        )
        return

    await state.update_data(
        user_id=user_id,
        training_posts=posts,
        current_post_index=0,
        rated_count=0,
        last_media_ids=[],
        last_activity_ts=datetime.utcnow().timestamp(),
        nudge_stage=0,
        is_retrain=True,
    )
    await state.set_state(TrainingStates.rating_posts)

    await _start_training_session(chat_id, user_id, message_manager, state)


@router.callback_query(F.data == "add_channel")
async def on_add_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Prompt user to add a channel."""
    await callback.answer()
    await state.set_state(TrainingStates.waiting_for_channel)
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("add_channel_prompt"),
            reply_markup=get_add_channel_keyboard(lang),
        )
    except Exception:
        pass


@router.message(TrainingStates.waiting_for_channel)
async def on_channel_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle channel username input."""
    channel_input = message.text.strip()
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = message.from_user.id
    
    await api.update_activity(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Validate input
    if not channel_input.startswith("@") and not channel_input.startswith("https://t.me/"):
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("invalid_channel_username"),
            auto_delete_after=5.0
        )
        return
    
    # Extract username
    if channel_input.startswith("https://t.me/"):
        username = "@" + channel_input.split("/")[-1]
    else:
        username = channel_input
    
    # Show loading
    await message_manager.send_ephemeral(
        message.chat.id,
        texts.get("checking_channel", username=username),
        tag="loading"
    )
    
    # Try to join and scrape channel
    join_result = await user_bot.join_channel(username)
    
    if join_result and join_result.get("success"):
        # Scrape channel FIRST (this creates the channel in DB)
        await user_bot.scrape_channel(username, limit=settings.posts_per_channel)
        
        # Now add to user's channels (channel exists in DB after scraping)
        await api.add_user_channel(user_id, username, is_for_training=True)
        await api.create_log(user_id, "channel_added", username)
        
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("channel_added", username=username),
            auto_delete_after=3.0
        )
        
        # Return to onboarding
        await state.clear()
        await message_manager.send_system(
            message.chat.id,
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang),
            tag="menu"
        )
    else:
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("cannot_access_channel", username=username),
            auto_delete_after=5.0
        )


@router.callback_query(F.data == "skip_add_channel")
async def on_skip_add_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Skip adding custom channel."""
    await callback.answer()
    await state.clear()
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang),
        )
    except Exception:
        pass


@router.callback_query(F.data == "back_to_start")
async def on_back_to_start(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Go back to start menu."""
    await callback.answer()
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    name = escape_md(callback.from_user.first_name or "there")
    
    try:
        await callback.message.edit_text(
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
        )
    except Exception:
        pass


@router.callback_query(F.data == "back_to_onboarding")
async def on_back_to_onboarding(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Go back to onboarding menu."""
    await callback.answer()
    await state.clear()
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang),
        )
    except Exception:
        pass
