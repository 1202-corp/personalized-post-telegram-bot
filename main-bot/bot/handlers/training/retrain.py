"""Retraining handlers for training flow."""

import logging
import asyncio
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext

from bot.core import MessageManager, get_texts, get_settings
from bot.core.states import TrainingStates
from bot.services import get_core_api, get_user_bot
from .helpers import _get_user_lang
from .flow import _start_training_session

logger = logging.getLogger(__name__)
router = Router()
settings = get_settings()


async def start_full_retrain(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start a new full retraining session using user's current channels."""
    api = get_core_api()
    user_bot = get_user_bot()

    await api.update_activity(user_id)
    await api.update_user(user_id, status="training")

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    default_channels = settings.default_training_channels.split(",")
    # Use set to avoid duplicates
    channels_set = set()
    for ch in default_channels:
        ch_clean = ch.strip().lstrip("@").lower()
        if ch_clean:
            channels_set.add(ch_clean)

    # Add default channels to user's channel list if not already added
    # This ensures users keep their training channels even if defaults change in .env
    for default_channel in default_channels:
        channel_username = default_channel.strip().lstrip("@")
        if channel_username:
            # Try to add as training channel (will be ignored if already exists)
            await api.channels.add_user_channel(
                user_id,
                channel_username,
                is_bonus=False
            )

    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        username = ch.get("username")
        if username:
            channels_set.add(username.lower())
    
    channels_to_scrape = [f"@{ch}" for ch in channels_set][:3]
    # Only scrape channels that need refresh (TTL check)
    need_refresh = await api.get_channels_need_refresh(channels_to_scrape)
    if need_refresh:
        await message_manager.send_system(
            chat_id,
            texts.get("fetching_posts"),
            tag="menu",
        )
        scrape_tasks = [
            user_bot.scrape_channel(ch, limit=settings.training_recent_posts_per_channel)
            for ch in need_refresh
        ]
        await asyncio.gather(*scrape_tasks, return_exceptions=True)

    await state.update_data(
        user_id=user_id,
        is_retrain=True,
    )

    from bot.core import get_retrain_keyboard
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
    """Start an additional short training flow focused on a bonus channel."""
    api = get_core_api()
    user_bot = get_user_bot()

    await api.update_activity(user_id)
    await api.update_user(user_id, status="training")

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    # Only scrape if channel needs refresh (TTL check)
    need_refresh = await api.get_channels_need_refresh([username])
    if need_refresh:
        await message_manager.send_system(
            chat_id,
            texts.get("fetching_posts"),
            tag="menu",
        )
        try:
            await user_bot.scrape_channel(username, limit=settings.training_recent_posts_per_channel)
        except Exception:
            pass

    await state.update_data(
        bonus_channel_username=username,
        is_bonus_training=True,
    )

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
    await message_manager.send_toast(callback)
    username = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    api = get_core_api()

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    channels_to_scrape = [username]

    posts = await api.get_training_posts(
        user_id,
        channels_to_scrape,
        settings.training_recent_posts_per_channel,
    )

    if not posts:
        await state.clear()
        from bot.core import get_feed_keyboard
        channels = await api.get_user_channels_with_meta(user_id)
        mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
        await message_manager.send_system(
            chat_id,
            texts.get("bonus_training_no_posts", username=username),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=False, mailing_any_on=mailing_any_on),
            tag="menu",
        )
        return

    # Build initial queue (first N posts from pool, not all)
    initial_count = min(len(posts), settings.training_initial_posts_per_channel)
    initial_queue = list(range(initial_count))
    
    await state.update_data(
        user_id=user_id,
        training_posts=posts,
        current_post_index=0,
        rated_count=0,
        training_queue=initial_queue,
        initial_queue_size=len(initial_queue),  # Save initial size for progress display
        shown_indices=[],
        likes_count=0,
        dislikes_count=0,
        skips_count=0,
        extra_from_dislike_used=0,
        extra_from_skip_used=0,
        last_media_ids=[],
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
    await message_manager.send_toast(callback)
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    api = get_core_api()
    user_bot = get_user_bot()

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    default_channels = settings.default_training_channels.split(",")
    channels_to_scrape = [ch.strip() for ch in default_channels]

    # Add default channels to user's channel list if not already added
    # This ensures users keep their training channels even if defaults change in .env
    for default_channel in default_channels:
        channel_username = default_channel.strip().lstrip("@")
        if channel_username:
            # Try to add as training channel (will be ignored if already exists)
            await api.channels.add_user_channel(
                user_id,
                channel_username,
                is_bonus=False
            )

    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        if ch.get("username"):
            channels_to_scrape.append(f"@{ch['username']}")

    posts = await api.get_training_posts(
        user_id,
        channels_to_scrape[:3],
        settings.training_recent_posts_per_channel,
    )

    if not posts:
        await state.clear()
        await message_manager.send_temporary(
            chat_id,
            texts.get("no_posts_training"),
            auto_delete_after=5.0,
        )
        return

    # Очередь: N1 первого канала, затем N2 второго (API вернул в таком порядке). Прогресс — общий.
    ch_names = set()
    for p in posts:
        ch = (p.get("channel_username") or "").strip().lstrip("@").lower()
        if ch:
            ch_names.add(ch)
    num_channels = len(ch_names) or 1
    initial_per_channel = settings.training_initial_posts_per_channel
    initial_queue_size = initial_per_channel * num_channels
    initial_queue = list(range(min(initial_queue_size, len(posts))))
    
    await state.update_data(
        user_id=user_id,
        training_posts=posts,
        current_post_index=0,
        rated_count=0,
        training_queue=initial_queue,
        initial_queue_size=len(initial_queue),  # Save initial size for progress display
        shown_indices=[],
        likes_count=0,
        dislikes_count=0,
        skips_count=0,
        extra_from_dislike_used=0,
        extra_from_skip_used=0,
        last_media_ids=[],
        is_retrain=True,
    )
    await state.set_state(TrainingStates.rating_posts)

    await _start_training_session(chat_id, user_id, message_manager, state)

