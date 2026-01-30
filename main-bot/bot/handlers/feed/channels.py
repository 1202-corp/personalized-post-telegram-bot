"""My channels and channel detail handlers."""

import html
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bot.core import (
    MessageManager, get_texts,
    get_feed_keyboard, get_channels_list_keyboard, get_channel_detail_keyboard,
    get_channels_view_keyboard,
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


def _channel_detail_text(detail: dict, texts: dict) -> str:
    """Build channel detail message text."""
    title = html.escape(detail.get("title") or "")
    username = (detail.get("username") or "").lstrip("@") or "—"
    posts = detail.get("posts_received_count", 0)
    tpl = texts.get(
        "channel_detail_stats",
        "<b>{title}</b>\n@{username}\n\n📊 Posts received: {count}",
    )
    text = tpl.format(title=title or "Channel", username=username, count=posts)
    desc = detail.get("description")
    if desc and desc.strip():
        desc_tpl = texts.get(
            "channel_detail_description",
            "📝 Description:\n<blockquote>{description}</blockquote>",
        )
        text += "\n\n" + desc_tpl.format(description=html.escape(desc.strip()))
    return text


async def _send_channel_detail_message(
    chat_id: int,
    detail: dict,
    text: str,
    keyboard: InlineKeyboardMarkup,
    message_manager: MessageManager,
    api,
    tag: str = "menu",
) -> None:
    """Send or edit channel detail (with avatar if available)."""
    avatar_file_id = detail.get("avatar_telegram_file_id")
    has_avatar = detail.get("has_avatar", False)
    channel_id = detail.get("id")
    if avatar_file_id:
        await message_manager.send_system(
            chat_id, text, reply_markup=keyboard, tag=tag, photo=avatar_file_id,
        )
    elif has_avatar and channel_id:
        avatar_bytes = await api.get_channel_avatar_bytes(channel_id)
        if avatar_bytes:
            await message_manager.send_system(
                chat_id, text, reply_markup=keyboard, tag=tag,
                photo_bytes=avatar_bytes, photo_filename="avatar.jpg",
            )
            return
    await show_menu(chat_id, text, keyboard, message_manager, tag)


async def _build_my_channels_content(api, user_id: int, texts: dict, lang: str):
    """Return (text, keyboard) for My Channels screen."""
    channels = await api.get_user_channels_with_meta(user_id)
    user_data = await api.get_user(user_id)
    has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
    limit = bonus_channel_limit(user_data)
    bonus_count = (user_data or {}).get("bonus_channels_count", 0)
    slots_left = max(0, limit - bonus_count)
    desc_tpl = texts.get("your_channels_description", "You can add {count} more channel(s).")
    description_line = "<blockquote>" + desc_tpl.format(count=slots_left) + "</blockquote>"
    if not channels:
        text = texts.get("no_user_channels", "You have no channels yet.") + "\n\n" + description_line
        keyboard = get_channels_view_keyboard(lang, has_bonus_channel=has_bonus)
    else:
        text = texts.get("your_channels_header", "📋 Your Channels:") + "\n\n" + description_line
        keyboard = get_channels_list_keyboard(channels, lang)
    return text, keyboard


@router.callback_query(F.data == "add_channel_feed")
async def on_add_channel_feed(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext,
):
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    user_data = await api.get_user(user_id)
    limit = bonus_channel_limit(user_data)
    count = (user_data or {}).get("bonus_channels_count", 0)
    if count >= limit:
        await message_manager.send_toast(
            callback,
            text=texts.get("add_channel_limit_reached", "You can't add a channel. Limit reached."),
            show_alert=True,
        )
        return
    await message_manager.send_toast(callback)
    await state.set_state(FeedStates.adding_channel)
    await message_manager.delete_temporary(callback.message.chat.id, tag="bonus_nudge")
    from bot.core import get_add_channel_keyboard
    await show_menu(
        callback.message.chat.id,
        texts.get("add_channel_prompt"),
        get_add_channel_keyboard(lang),
        message_manager,
    )


@router.message(FeedStates.adding_channel)
async def on_channel_feed_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Handle channel input from feed menu (add channel flow)."""
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
        await user_bot.scrape_channel(username, limit=settings.training_recent_posts_per_channel)
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


@router.callback_query(F.data == "my_channels")
async def on_my_channels(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    text, keyboard = await _build_my_channels_content(api, user_id, texts, lang)
    await show_menu(callback.message.chat.id, text, keyboard, message_manager)


@router.callback_query(F.data.startswith("channel_detail:"))
async def on_channel_detail(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    channel_id = int(callback.data.split(":")[1])
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    detail = await api.get_user_channel_detail(user_id, channel_id)
    if not detail:
        await message_manager.send_temporary(
            callback.message.chat.id,
            texts.get("channel_not_found", "Channel not found."),
            auto_delete_after=5.0,
        )
        return
    text = _channel_detail_text(detail, texts)
    mailing_enabled = detail.get("mailing_enabled", True)
    can_delete = detail.get("is_bonus", False)
    keyboard = get_channel_detail_keyboard(channel_id, mailing_enabled, can_delete, lang)
    await _send_channel_detail_message(
        callback.message.chat.id, detail, text, keyboard, message_manager, api,
    )


@router.callback_query(F.data.startswith("channel_mailing_toggle:"))
async def on_channel_mailing_toggle(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    channel_id = int(callback.data.split(":")[1])
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    detail = await api.get_user_channel_detail(user_id, channel_id)
    if not detail:
        return
    new_value = not detail.get("mailing_enabled", True)
    if new_value:
        user_data = await api.get_user(user_id)
        if user_data and user_data.get("user_role") not in ("member", "admin"):
            feed_eligible = await api.get_feed_eligible(user_id)
            if not (feed_eligible and feed_eligible.get("eligible")):
                await message_manager.send_temporary(
                    callback.message.chat.id,
                    texts.get("feed_complete_training_first", "Complete training first to unlock your feed and mailing."),
                    auto_delete_after=5.0,
                )
                return
    result = await api.patch_user_channel_mailing(user_id, channel_id, new_value)
    if not result:
        return
    detail = await api.get_user_channel_detail(user_id, channel_id)
    if not detail:
        return
    text = _channel_detail_text(detail, texts)
    can_delete = detail.get("is_bonus", False)
    keyboard = get_channel_detail_keyboard(channel_id, detail.get("mailing_enabled", True), can_delete, lang)
    await _send_channel_detail_message(
        callback.message.chat.id, detail, text, keyboard, message_manager, api,
    )


@router.callback_query(F.data.startswith("channel_delete:"))
async def on_channel_delete_confirm(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    channel_id = int(callback.data.split(":")[1])
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=texts.get("confirm_btn_yes", "✅ Yes"), callback_data=f"channel_delete_confirm:{channel_id}"),
            InlineKeyboardButton(text=texts.get("confirm_btn_no", "❌ No"), callback_data="my_channels"),
        ],
    ])
    await message_manager.send_temporary(
        callback.message.chat.id,
        texts.get("channel_delete_confirm", "Remove this channel from your list?"),
        reply_markup=confirm_keyboard,
        tag=f"channel_delete_confirm:{channel_id}",
        auto_delete_after=60.0,
    )


@router.callback_query(F.data.startswith("channel_delete_confirm:"))
async def on_channel_delete_do(callback: CallbackQuery, message_manager: MessageManager):
    await message_manager.send_toast(callback)
    channel_id = int(callback.data.split(":")[1])
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    ok = await api.delete_user_channel(user_id, channel_id)
    if not ok:
        await message_manager.send_temporary(
            callback.message.chat.id,
            texts.get("channel_delete_failed", "Could not remove channel."),
            auto_delete_after=5.0,
        )
        return
    text, keyboard = await _build_my_channels_content(api, user_id, texts, lang)
    await show_menu(callback.message.chat.id, text, keyboard, message_manager)
