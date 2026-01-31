"""Onboarding handlers for training flow."""

import json
import logging
import asyncio

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext

from bot.core import (
    MessageManager, get_texts, get_settings,
    get_start_keyboard, get_onboarding_keyboard, get_add_channel_keyboard,
    get_bonus_channel_keyboard, get_how_it_works_keyboard,
)
from bot.core.states import TrainingStates
from bot.services import get_core_api, get_user_bot
import html
from .helpers import _get_user_lang
from .flow import _start_training_session, finish_training_flow

logger = logging.getLogger(__name__)
router = Router()
settings = get_settings()


@router.message(F.web_app_data)
async def on_web_app_data(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Handle data sent from MiniApp via tg.sendData()."""
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
        existing_state = await state.get_data()
        is_bonus_training = existing_state.get("is_bonus_training", False)
        is_retrain = existing_state.get("is_retrain", False)
        
        await state.update_data(
            rated_count=rated_count,
            user_id=user_id,
            is_bonus_training=is_bonus_training,
            is_retrain=is_retrain,
        )
        
        await finish_training_flow(chat_id, message_manager, state)
    
    elif action == "interaction":
        post_id = data.get("post_id")
        interaction_type = data.get("type")
        
        if post_id and interaction_type and interaction_type != "skip":
            await api.create_interaction(user_id, post_id, interaction_type)
    
    else:
        logger.warning(f"Unknown web_app_data action: {action}")


@router.callback_query(F.data == "start_training")
async def on_start_training(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Handle Start Training button - scrape posts and show MiniApp/chat choice."""
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = callback.from_user.id
    await api.update_activity(user_id)
    
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    default_channels = settings.default_training_channels.split(",")
    # Use set to avoid duplicates
    channels_set = set()
    for ch in default_channels:
        ch_clean = ch.strip().lstrip("@").lower()
        if ch_clean:
            channels_set.add(ch_clean)
    
    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        username = ch.get("username")
        if username:
            channels_set.add(username.lower())
    
    channels_to_scrape = [f"@{ch}" for ch in channels_set][:3]
    # Статус training — чтобы MiniApp мог загрузить посты (POST /posts/training только при status=training)
    await api.update_user(user_id, status="training")
    # Only scrape channels that need refresh (not in DB or metadata older than TTL)
    need_refresh = await api.get_channels_need_refresh(channels_to_scrape)
    if need_refresh:
        try:
            await callback.message.edit_text(texts.get("fetching_posts"))
        except Exception:
            pass
        user_bot = get_user_bot()
        scrape_tasks = [
            user_bot.scrape_channel(ch, limit=settings.training_recent_posts_per_channel, for_training=True)
            for ch in need_refresh
        ]
        await asyncio.gather(*scrape_tasks, return_exceptions=True)
    
    try:
        await callback.message.edit_text(
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang, user_id, channels_to_scrape[:3]),
        )
    except Exception:
        pass


@router.callback_query(F.data == "how_it_works")
async def on_how_it_works(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show how the bot works."""
    await message_manager.send_toast(callback)
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("how_it_works"),
        reply_markup=get_how_it_works_keyboard(lang),
        tag="menu"
    )


@router.callback_query(F.data == "confirm_training")
async def on_confirm_training(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Start the actual training process."""
    await message_manager.send_toast(callback, "🚀 Starting training...")
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = callback.from_user.id
    
    await api.update_activity(user_id)
    await api.update_user(user_id, status="training")
    
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("fetching_posts"),
        tag="menu"
    )
    
    # Build list of channels to use for training (defaults + user channels)
    default_channels = settings.default_training_channels.split(",")
    channels_set = set()
    
    # Add default channels (do not add to user list here — only on training completion)
    for ch in default_channels:
        ch_clean = ch.strip().lstrip("@").lower()
        if ch_clean:
            channels_set.add(ch_clean)
    
    # Add user's own channels
    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        username = ch.get("username")
        if username:
            channels_set.add(username.lower())
    
    channels_to_use = [f"@{ch}" for ch in channels_set]
    
    # Request posts for training from API (use training_recent_posts_per_channel for full pool)
    posts = await api.get_training_posts(
        user_id,
        channels_to_use,
        settings.training_recent_posts_per_channel,
    )
    
    if not posts:
        lang = await _get_user_lang(user_id)
        texts = get_texts(lang)
        await message_manager.send_toast(
            callback,
            text=texts.get("services_unavailable", "Sorry, services are unavailable. Please try again later."),
            show_alert=True,
        )
        from bot.core import get_start_keyboard
        name = html.escape(callback.from_user.first_name or "there")
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
            tag="menu"
        )
        return
    
    # Очередь: по initial_per_channel постов с КАЖДОГО канала (не первые N из всего пула).
    # API вернул посты в порядке: [все по каналу 1], [все по каналу 2], ... — группируем индексы по каналу.
    training_posts = list(posts)
    initial_per_channel = settings.training_initial_posts_per_channel

    def _channel_key(p):
        return (p.get("channel_username") or "").strip().lstrip("@").lower() or "unknown"

    # Порядок каналов: как впервые встречаются в training_posts
    channel_order = []
    seen_ch = set()
    for p in training_posts:
        ch = _channel_key(p)
        if ch not in seen_ch:
            seen_ch.add(ch)
            channel_order.append(ch)

    # Индексы по каналам (в том же порядке, что и посты)
    channel_to_indices = {}
    for i, p in enumerate(training_posts):
        ch = _channel_key(p)
        if ch not in channel_to_indices:
            channel_to_indices[ch] = []
        channel_to_indices[ch].append(i)

    # Берём до initial_per_channel постов с каждого канала по очереди
    initial_queue = []
    per_channel_taken = {}
    for ch in channel_order:
        indices = channel_to_indices.get(ch, [])
        take = min(initial_per_channel, len(indices))
        initial_queue.extend(indices[:take])
        per_channel_taken[ch] = take

    num_channels = len(channel_order) or 1
    expected_initial_count = initial_per_channel * num_channels
    actual_initial_count = len(initial_queue)
    pool_post_ids = [p.get("id") for p in training_posts]
    initial_queue_post_ids = [training_posts[i].get("id") for i in initial_queue]

    logger.info(
        "[TRAINING] pool: total=%s, post_ids=%s",
        len(training_posts),
        pool_post_ids,
    )
    logger.info(
        "[TRAINING] initial queue (up to %s per channel): indices=%s, post_ids=%s, per_channel=%s",
        initial_per_channel,
        initial_queue,
        initial_queue_post_ids,
        per_channel_taken,
    )
    logger.info(
        "[TRAINING] initial count: expected (initial_per_channel*num_channels)=%s*%s=%s, actual=%s, channels=%s",
        initial_per_channel,
        num_channels,
        expected_initial_count,
        actual_initial_count,
        num_channels,
    )
    
    await state.update_data(
        user_id=user_id,
        training_posts=training_posts,
        training_channel_usernames=channel_order,  # Added to user list only on completion
        current_post_index=0,
        rated_count=0,
        training_queue=initial_queue,
        initial_queue_size=len(initial_queue),  # Save initial size for progress display
        shown_indices=[],  # Track already shown posts to prevent duplicates
        likes_count=0,
        dislikes_count=0,
        skips_count=0,
        extra_from_dislike_used=0,
        extra_from_skip_used=0,
    )
    await state.set_state(TrainingStates.rating_posts)
    
    await _start_training_session(callback.message.chat.id, callback.from_user.id, message_manager, state)


@router.callback_query(F.data == "add_channel")
async def on_add_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Prompt user to add a channel."""
    await message_manager.send_toast(callback)
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
    
    # Delete user's message
    await message_manager.delete_user_message(message)
    
    if not channel_input.startswith("@") and not channel_input.startswith("https://t.me/"):
        await message_manager.send_temporary(
            message.chat.id,
            texts.get("invalid_channel_username"),
            auto_delete_after=5.0
        )
        return
    
    if channel_input.startswith("https://t.me/"):
        username = "@" + channel_input.split("/")[-1]
    else:
        username = channel_input
    
    await message_manager.send_temporary(
        message.chat.id,
        texts.get("checking_channel", username=username),
        tag="loading"
    )
    
    join_result = await user_bot.join_channel(username)
    
    if join_result and join_result.get("success"):
        await user_bot.scrape_channel(username, limit=settings.training_recent_posts_per_channel, for_training=True)
        await api.add_user_channel(user_id, username, is_bonus=False)
        
        await message_manager.delete_temporary(message.chat.id, tag="loading")
        await message_manager.send_temporary(
            message.chat.id,
            texts.get("channel_added", username=username),
            auto_delete_after=3.0
        )
        
        await state.clear()
        await message_manager.send_system(
            message.chat.id,
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang),
            tag="menu"
        )
    else:
        await message_manager.delete_temporary(message.chat.id, tag="loading")
        await message_manager.send_temporary(
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
    await message_manager.send_toast(callback)
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
    message_manager: MessageManager,
    state: FSMContext
):
    """Go back to start menu, or to feed if user is member/admin (e.g. cancelled bonus training)."""
    await message_manager.send_toast(callback)

    state_data = await state.get_data()
    await state.clear()

    await message_manager.delete_temporary(callback.message.chat.id, tag="training_post_controls")

    from bot.services import get_core_api
    from bot.core import get_start_keyboard, get_feed_keyboard
    api = get_core_api()
    user_id = callback.from_user.id
    user_data = await api.get_user(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    name = html.escape(callback.from_user.first_name or "there")

    # If member/admin (e.g. bonus training or channel retrain), go to feed and restore status
    if user_data and user_data.get("user_role") in ("member", "admin"):
        if state_data.get("is_bonus_training") or state_data.get("is_channel_retrain") or user_data.get("status") == "training":
            await api.update_user(user_id, status="active")
        has_bonus = (user_data or {}).get("bonus_channels_count", 0) >= 1
        channels = await api.get_user_channels_with_meta(user_id)
        mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
        success = await message_manager.edit_system(
            callback.message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
            tag="menu",
        )
        if not success:
            await message_manager.send_system(
                callback.message.chat.id,
                texts.get("feed_ready"),
                reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
                tag="menu",
            )
        return

    # Guest: show start menu
    success = await message_manager.edit_system(
        callback.message.chat.id,
        texts.get("welcome", name=name),
        reply_markup=get_start_keyboard(lang),
        tag="menu",
    )
    if not success:
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
            tag="menu",
        )


@router.callback_query(F.data == "back_to_onboarding")
async def on_back_to_onboarding(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Go back to onboarding menu."""
    await message_manager.send_toast(callback)
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

