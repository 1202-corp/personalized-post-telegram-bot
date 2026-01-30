"""Back to feed and cancel handlers."""

import html
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.core import (
    MessageManager, get_texts, get_feed_keyboard,
    get_start_keyboard, get_onboarding_keyboard,
)
from bot.services import get_core_api
from bot.utils import get_user_lang as _get_user_lang

from .common import show_menu

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "back_to_feed")
async def on_back_to_feed(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_id = callback.from_user.id
    user_data = await api.get_user(user_id)
    if user_data and user_data.get("user_role") not in ("member", "admin"):
        feed_eligible = await api.get_feed_eligible(user_id)
        if not (feed_eligible and feed_eligible.get("eligible")):
            lang = await _get_user_lang(user_id)
            texts = get_texts(lang)
            await show_menu(
                callback.message.chat.id,
                texts.get("feed_complete_training_first", "Complete training first to unlock your feed and mailing."),
                get_start_keyboard(lang),
                message_manager,
            )
            return
    has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
    channels = await api.get_user_channels_with_meta(user_id)
    mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    await show_menu(
        callback.message.chat.id,
        texts.get("feed_ready"),
        get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
        message_manager,
    )


@router.callback_query(F.data == "cancel")
async def on_cancel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Cancel current operation; return to feed, training intro, or start."""
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    await message_manager.send_toast(callback, texts.get("cancelled"))
    current_state = await state.get_state()
    state_data = await state.get_data()
    await state.clear()
    api = get_core_api()
    user_id = callback.from_user.id
    user_data = await api.get_user(user_id)

    if user_data and user_data.get("user_role") in ("member", "admin"):
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1
        channels = await api.get_user_channels_with_meta(user_id)
        mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
        await show_menu(
            callback.message.chat.id,
            texts.get("feed_ready"),
            get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
            message_manager,
        )
    elif current_state and "training" in str(current_state).lower():
        await show_menu(
            callback.message.chat.id,
            texts.get("training_intro"),
            get_onboarding_keyboard(lang),
            message_manager,
        )
    elif current_state and "adding" in str(current_state).lower():
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
        if user_data and user_data.get("user_role") in ("member", "admin"):
            channels = await api.get_user_channels_with_meta(user_id)
            mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
            await show_menu(
                callback.message.chat.id,
                texts.get("feed_ready"),
                get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
                message_manager,
            )
        else:
            await show_menu(
                callback.message.chat.id,
                texts.get("training_intro"),
                get_onboarding_keyboard(lang),
                message_manager,
            )
    else:
        name = html.escape(callback.from_user.first_name or "there")
        await show_menu(
            callback.message.chat.id,
            texts.get("welcome", name=name),
            get_start_keyboard(lang),
            message_manager,
        )
