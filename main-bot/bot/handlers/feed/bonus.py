"""Bonus channel handlers: claim, add, skip."""

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.core import (
    MessageManager, get_texts,
    get_feed_keyboard, get_bonus_channel_keyboard, get_add_channel_keyboard,
)
from bot.core.config import get_settings
from bot.core.states import FeedStates
from bot.services import get_core_api, get_user_bot
from bot.utils import get_user_lang as _get_user_lang
from bot.handlers.training.retrain import start_bonus_training

from .common import bonus_channel_limit, show_menu

logger = logging.getLogger(__name__)
router = Router()
settings = get_settings()


@router.callback_query(F.data == "claim_bonus")
async def on_claim_bonus(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_id = callback.from_user.id
    await api.update_activity(user_id)
    user_data = await api.get_user(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await message_manager.send_temporary(
            callback.message.chat.id,
            texts.get("already_have_bonus"),
            auto_delete_after=5.0,
        )
        return
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("bonus_channel"),
        reply_markup=get_bonus_channel_keyboard(lang),
        tag="menu",
    )


@router.callback_query(F.data == "add_bonus_channel")
async def on_add_bonus_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext,
):
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    await state.set_state(FeedStates.adding_bonus_channel)
    await message_manager.delete_temporary(callback.message.chat.id, tag="bonus_nudge")
    await show_menu(
        callback.message.chat.id,
        texts.get("add_channel_prompt"),
        get_add_channel_keyboard(lang),
        message_manager,
    )


@router.message(FeedStates.adding_bonus_channel)
async def on_bonus_channel_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext,
):
    channel_input = message.text.strip()
    await message_manager.delete_user_message(message)
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = message.from_user.id
    await api.update_activity(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    user_data = await api.get_user(user_id)
    limit = bonus_channel_limit(user_data)
    count = (user_data or {}).get("bonus_channels_count", 0)
    if count >= limit:
        await state.clear()
        await message_manager.send_temporary(
            message.chat.id,
            texts.get("add_channel_limit_reached", "You can't add a channel. Limit reached."),
            auto_delete_after=5.0,
        )
        has_bonus = (user_data or {}).get("bonus_channels_count", 0) >= 1
        channels = await api.get_user_channels_with_meta(user_id)
        mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
        await message_manager.send_system(
            message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
            tag="menu",
        )
        return
    if channel_input.startswith("https://t.me/"):
        username = "@" + channel_input.split("/")[-1]
    elif channel_input.startswith("@"):
        username = channel_input
    else:
        await message_manager.send_temporary(
            message.chat.id,
            texts.get("invalid_channel_username_short"),
            auto_delete_after=5.0,
        )
        return
    await message_manager.send_temporary(
        message.chat.id,
        texts.get("adding_bonus_channel", username=username),
        tag="loading",
    )
    join_result = await user_bot.join_channel(username)
    if join_result and join_result.get("success"):
        await user_bot.scrape_channel(username, limit=settings.training_recent_posts_per_channel, for_training=True)
        user_obj = message.from_user
        await api.get_or_create_user(
            telegram_id=user_id,
            username=user_obj.username,
            first_name=user_obj.first_name,
            last_name=user_obj.last_name,
            language_code=user_obj.language_code,
        )
        add_result = await api.add_user_channel(user_id, username, is_bonus=True)
        if add_result:
            await api.update_user(user_id, bonus_channels_count=count + 1)
        await state.clear()
        await message_manager.delete_temporary(message.chat.id, tag="loading")
        await start_bonus_training(
            chat_id=message.chat.id,
            user_id=user_id,
            username=username,
            message_manager=message_manager,
            state=state,
        )
    else:
        await message_manager.delete_temporary(message.chat.id, tag="loading")
        await message_manager.send_temporary(
            message.chat.id,
            texts.get("cannot_access_channel", username=username),
            auto_delete_after=5.0,
        )


@router.callback_query(F.data == "skip_bonus")
async def on_skip_bonus(callback: CallbackQuery, message_manager: MessageManager):
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    channels = await api.get_user_channels_with_meta(user_id)
    mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
    await message_manager.send_toast(callback, texts.get("you_can_claim_later"))
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("feed_ready"),
        reply_markup=get_feed_keyboard(lang, has_bonus_channel=False, mailing_any_on=mailing_any_on),
        tag="menu",
    )
