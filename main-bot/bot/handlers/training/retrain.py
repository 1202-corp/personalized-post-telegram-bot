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

    # Do not add channels here — only on training completion (see finish_training_flow)

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
            user_bot.scrape_channel(ch, limit=settings.training_recent_posts_per_channel, for_training=True)
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


async def start_channel_retrain(
    chat_id: int,
    user_id: int,
    channel_id: int,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start retraining for a single channel (from channel detail menu)."""
    api = get_core_api()
    user_bot = get_user_bot()
    detail = await api.get_user_channel_detail(user_id, channel_id)
    if not detail:
        lang = await _get_user_lang(user_id)
        texts = get_texts(lang)
        await message_manager.send_system(
            chat_id,
            texts.get("channel_not_found", "Channel not found."),
            tag="menu",
        )
        return
    username = detail.get("username") or ""
    if not username:
        username = f"channel_{channel_id}"
    if not username.startswith("@"):
        username = f"@{username}"

    await api.update_activity(user_id)
    await api.update_user(user_id, status="training")

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    need_refresh = await api.get_channels_need_refresh([username])
    if need_refresh:
        await message_manager.send_temporary(
            chat_id,
            texts.get("fetching_posts", "Fetching posts..."),
            tag="loading",
        )
        try:
            await user_bot.scrape_channel(username, limit=settings.training_recent_posts_per_channel, for_training=True)
        except Exception:
            pass

    await state.update_data(
        retrain_channel_id=channel_id,
        is_retrain=True,
    )

    from bot.core import get_retrain_keyboard
    intro_text = texts.get("retrain_intro", default="🔄 Переобучение модели")
    await message_manager.send_system(
        chat_id,
        intro_text,
        reply_markup=get_retrain_keyboard_channel(lang, user_id, username, channel_id),
        tag="menu",
    )


def get_retrain_keyboard_channel(lang: str, user_id: int, username: str, channel_id: int) -> InlineKeyboardMarkup:
    """Retrain keyboard for single channel: MiniApp, Rate in chat, Back."""
    t = get_texts(lang)
    miniapp_url = f"{settings.miniapp_url}?user_id={user_id}&channel={username.lstrip('@')}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t.get("retrain_btn_miniapp", default="📱 Переобучить в MiniApp"),
            web_app=WebAppInfo(url=miniapp_url),
        )],
        [InlineKeyboardButton(
            text=t.get("retrain_btn_chat", default="💬 Оценивать в чате"),
            callback_data=f"confirm_retrain_channel:{channel_id}",
        )],
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Назад"), callback_data=f"channel_detail:{channel_id}")],
    ])


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
        await message_manager.send_temporary(
            chat_id,
            texts.get("fetching_posts", "Fetching posts..."),
            tag="loading",
        )
        try:
            await user_bot.scrape_channel(username, limit=settings.training_recent_posts_per_channel, for_training=True)
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
        [InlineKeyboardButton(text=texts.get("settings_btn_back", default="⬅️ Назад"), callback_data="my_channels")],
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
    username_clean = username.strip().lstrip("@").lower()

    await state.update_data(
        user_id=user_id,
        training_posts=posts,
        training_channel_usernames=[username_clean],  # Added to user list only on completion
        training_bonus_usernames=[username_clean],  # This channel is bonus
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


@router.callback_query(F.data.startswith("confirm_retrain_channel:"))
async def on_confirm_retrain_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start single-channel retrain in chat mode (from channel detail)."""
    await message_manager.send_toast(callback)
    channel_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    api = get_core_api()

    detail = await api.get_user_channel_detail(user_id, channel_id)
    if not detail:
        lang = await _get_user_lang(user_id)
        texts = get_texts(lang)
        from bot.core import get_feed_keyboard
        channels = await api.get_user_channels_with_meta(user_id)
        mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
        await message_manager.send_system(
            chat_id,
            texts.get("channel_not_found", "Channel not found."),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=False, mailing_any_on=mailing_any_on),
            tag="menu",
        )
        return

    username = (detail.get("username") or "").strip()
    if not username.startswith("@"):
        username = f"@{username}"

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
            texts.get("no_posts_training", "No posts for this channel."),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=False, mailing_any_on=mailing_any_on),
            tag="menu",
        )
        return

    initial_count = min(len(posts), settings.training_initial_posts_per_channel)
    initial_queue = list(range(initial_count))
    username_clean = username.strip().lstrip("@").lower()

    await state.update_data(
        user_id=user_id,
        training_posts=posts,
        training_channel_usernames=[username_clean],
        training_bonus_usernames=[],  # not adding channel, it's already in list
        current_post_index=0,
        rated_count=0,
        training_queue=initial_queue,
        initial_queue_size=len(initial_queue),
        shown_indices=[],
        likes_count=0,
        dislikes_count=0,
        skips_count=0,
        extra_from_dislike_used=0,
        extra_from_skip_used=0,
        last_media_ids=[],
        is_retrain=True,
        is_channel_retrain=True,
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

    # Do not add channels here — only on training completion (see finish_training_flow)

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

    # Очередь: по initial_per_channel постов с КАЖДОГО канала (не первые N из всего пула).
    def _channel_key(p):
        return (p.get("channel_username") or "").strip().lstrip("@").lower() or "unknown"

    channel_order = []
    seen_ch = set()
    for p in posts:
        ch = _channel_key(p)
        if ch not in seen_ch:
            seen_ch.add(ch)
            channel_order.append(ch)

    channel_to_indices = {}
    for i, p in enumerate(posts):
        ch = _channel_key(p)
        if ch not in channel_to_indices:
            channel_to_indices[ch] = []
        channel_to_indices[ch].append(i)

    initial_per_channel = settings.training_initial_posts_per_channel
    initial_queue = []
    per_channel_taken = {}
    for ch in channel_order:
        indices = channel_to_indices.get(ch, [])
        take = min(initial_per_channel, len(indices))
        initial_queue.extend(indices[:take])
        per_channel_taken[ch] = take

    num_channels = len(channel_order) or 1
    expected_initial_count = initial_per_channel * num_channels
    pool_post_ids = [p.get("id") for p in posts]
    initial_queue_post_ids = [posts[i].get("id") for i in initial_queue]

    logger.info("[TRAINING] (retrain) pool: total=%s, post_ids=%s", len(posts), pool_post_ids)
    logger.info(
        "[TRAINING] (retrain) initial queue (up to %s per channel): indices=%s, post_ids=%s, per_channel=%s",
        initial_per_channel,
        initial_queue,
        initial_queue_post_ids,
        per_channel_taken,
    )
    logger.info(
        "[TRAINING] (retrain) initial count: expected=%s, actual=%s, channels=%s",
        expected_initial_count,
        len(initial_queue),
        num_channels,
    )

    await state.update_data(
        user_id=user_id,
        training_posts=posts,
        training_channel_usernames=channel_order,  # Added to user list only on completion
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

