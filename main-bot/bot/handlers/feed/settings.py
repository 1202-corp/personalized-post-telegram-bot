"""Settings, retrain and mailing toggle handlers."""

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.core import MessageManager, get_texts, get_settings_keyboard, get_feed_keyboard
from bot.services import get_core_api
from bot.utils import get_user_lang as _get_user_lang
from bot.handlers.training.retrain import start_full_retrain

from .common import show_menu

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "retrain")
async def on_retrain_model(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start a new interactive retraining session on user's channels."""
    await message_manager.send_toast(callback)
    await start_full_retrain(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        message_manager=message_manager,
        state=state,
    )


@router.callback_query(F.data == "settings")
async def on_settings(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    await show_menu(
        callback.message.chat.id,
        texts.get("settings_title"),
        get_settings_keyboard(lang),
        message_manager,
    )


@router.callback_query(F.data == "mailing_toggle_all")
async def on_mailing_toggle_all(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    channels = await api.get_user_channels_with_meta(user_id)
    mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
    new_state = not mailing_any_on
    result = await api.patch_user_all_channels_mailing(user_id, new_state)
    if result is None:
        await message_manager.send_toast(
            callback,
            text=texts.get("error_generic", "Something went wrong."),
            show_alert=True,
        )
        return
    user_data = await api.get_user(user_id)
    has_bonus = (user_data or {}).get("bonus_channels_count", 0) >= 1
    await show_menu(
        callback.message.chat.id,
        texts.get("feed_ready"),
        get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=new_state),
        message_manager,
    )


@router.callback_query(F.data == "back_to_settings")
async def on_back_to_settings(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    await show_menu(
        callback.message.chat.id,
        texts.get("settings_title"),
        get_settings_keyboard(lang),
        message_manager,
    )
