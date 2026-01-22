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
from .helpers import _get_user_lang, _start_training_session

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

    await message_manager.send_system(
        chat_id,
        texts.get("fetching_posts"),
        tag="menu",
    )

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
    await api.create_log(user_id, "bonus_training_started", username)
    await api.update_user(user_id, status="training")

    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    await message_manager.send_system(
        chat_id,
        texts.get("fetching_posts"),
        tag="menu",
    )

    try:
        await user_bot.scrape_channel(username, limit=settings.posts_per_channel)
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
    await callback.answer()
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
        settings.posts_per_channel,
    )

    if not posts:
        await state.clear()
        from bot.core import get_feed_keyboard
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

