"""Feed action handlers (bonus channels, settings, channels management)."""

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bot.core import (
    MessageManager, get_texts,
    get_feed_keyboard, get_bonus_channel_keyboard,
    get_settings_keyboard, get_add_channel_keyboard,
    get_channels_list_keyboard, get_channel_detail_keyboard,
)
from bot.core.states import FeedStates
from bot.services import get_core_api, get_user_bot
import html
from bot.handlers.training.retrain import start_full_retrain, start_bonus_training

logger = logging.getLogger(__name__)
router = Router()


from bot.utils import get_user_lang as _get_user_lang
from bot.core.config import get_settings


def _bonus_channel_limit(user_data: dict) -> int:
    """Return max bonus channels from config: admin limit or member limit."""
    settings = get_settings()
    if user_data and user_data.get("user_role") == "admin":
        return settings.bonus_channel_limit_admin
    return settings.bonus_channel_limit_member


@router.callback_query(F.data == "claim_bonus")
async def on_claim_bonus(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show bonus channel claim option."""
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
            auto_delete_after=5.0
        )
        return
    
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("bonus_channel"),
        reply_markup=get_bonus_channel_keyboard(lang),
        tag="menu"
    )


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


@router.callback_query(F.data == "add_bonus_channel")
async def on_add_bonus_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Prompt for bonus channel."""
    await message_manager.send_toast(callback)
    
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    await state.set_state(FeedStates.adding_bonus_channel)
    
    # Use edit_system to ensure temporary messages are deleted
    success = await message_manager.edit_system(
        callback.message.chat.id,
        texts.get("add_channel_prompt"),
        reply_markup=get_add_channel_keyboard(lang),
        tag="menu"
    )
    if not success:
        # Fallback to send_system if edit fails
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("add_channel_prompt"),
            reply_markup=get_add_channel_keyboard(lang),
            tag="menu"
        )


@router.message(FeedStates.adding_bonus_channel)
async def on_bonus_channel_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle bonus channel input."""
    channel_input = message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass
    
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = message.from_user.id
    
    await api.update_activity(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    user_data = await api.get_user(user_id)
    limit = _bonus_channel_limit(user_data)
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
            tag="menu"
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
            auto_delete_after=5.0
        )
        return

    await message_manager.send_temporary(
        message.chat.id,
        texts.get("adding_bonus_channel", username=username),
        tag="loading"
    )

    join_result = await user_bot.join_channel(username)

    if join_result and join_result.get("success"):
        await user_bot.scrape_channel(username, limit=10)

        user_obj = message.from_user
        await api.get_or_create_user(
            telegram_id=user_id,
            username=user_obj.username,
            first_name=user_obj.first_name,
            last_name=user_obj.last_name,
            language_code=user_obj.language_code
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
            auto_delete_after=5.0
        )


@router.callback_query(F.data == "skip_bonus")
async def on_skip_bonus(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Skip bonus channel claim."""
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
        tag="menu"
    )


@router.callback_query(F.data == "add_channel_feed")
async def on_add_channel_feed(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Add a new channel from feed menu. Show toast if at limit."""
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    user_data = await api.get_user(user_id)
    limit = _bonus_channel_limit(user_data)
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
    
    # Use edit_system to ensure temporary messages are deleted
    success = await message_manager.edit_system(
        callback.message.chat.id,
        texts.get("add_channel_prompt"),
        reply_markup=get_add_channel_keyboard(lang),
        tag="menu"
    )
    if not success:
        # Fallback to send_system if edit fails
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("add_channel_prompt"),
            reply_markup=get_add_channel_keyboard(lang),
            tag="menu"
        )


@router.message(FeedStates.adding_channel)
async def on_channel_feed_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle channel input from feed menu - same as bonus channel flow."""
    channel_input = message.text.strip()
    await message_manager.delete_user_message(message)

    api = get_core_api()
    user_bot = get_user_bot()
    user_id = message.from_user.id

    await api.update_activity(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    user_data = await api.get_user(user_id)
    limit = _bonus_channel_limit(user_data)
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
            tag="menu"
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
            auto_delete_after=5.0
        )
        return
    
    await message_manager.send_temporary(
        message.chat.id,
        texts.get("adding_bonus_channel", username=username),
        tag="loading"
    )
    
    join_result = await user_bot.join_channel(username)
    
    if join_result and join_result.get("success"):
        await user_bot.scrape_channel(username, limit=10)
        
        user_obj = message.from_user
        await api.get_or_create_user(
            telegram_id=user_id,
            username=user_obj.username,
            first_name=user_obj.first_name,
            last_name=user_obj.last_name,
            language_code=user_obj.language_code
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
            auto_delete_after=5.0
        )


@router.callback_query(F.data == "settings")
async def on_settings(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show settings menu."""
    await message_manager.send_toast(callback)
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    # Use edit_system to ensure temporary messages are deleted
    success = await message_manager.edit_system(
        callback.message.chat.id,
        texts.get("settings_title"),
        reply_markup=get_settings_keyboard(lang),
        tag="menu"
    )
    if not success:
        # Fallback to send_system if edit fails
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("settings_title"),
            reply_markup=get_settings_keyboard(lang),
            tag="menu"
        )


@router.callback_query(F.data == "mailing_toggle_all")
async def on_mailing_toggle_all(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Toggle mailing for all user's channels. Per-channel status stays in sync (My channels -> channel shows same)."""
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
        await message_manager.send_toast(callback, text=texts.get("error_generic", "Something went wrong."), show_alert=True)
        return
    user_data = await api.get_user(user_id)
    has_bonus = (user_data or {}).get("bonus_channels_count", 0) >= 1
    success = await message_manager.edit_system(
        callback.message.chat.id,
        texts.get("feed_ready"),
        reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=new_state),
        tag="menu",
    )
    if not success:
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=new_state),
            tag="menu",
        )


@router.callback_query(F.data == "my_channels")
async def on_my_channels(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show user's channels as inline buttons (one per channel) + Back."""
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    channels = await api.get_user_channels_with_meta(user_id)
    user_data = await api.get_user(user_id)
    has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
    limit = _bonus_channel_limit(user_data)
    bonus_count = (user_data or {}).get("bonus_channels_count", 0)
    slots_left = max(0, limit - bonus_count)
    desc_tpl = texts.get("your_channels_description", "You can add {count} more channel(s).")
    description_line = "<blockquote>" + desc_tpl.format(count=slots_left) + "</blockquote>"
    if not channels:
        text = texts.get("no_user_channels", "You have no channels yet.") + "\n\n" + description_line
        from bot.core import get_channels_view_keyboard
        keyboard = get_channels_view_keyboard(lang, has_bonus_channel=has_bonus)
    else:
        text = texts.get("your_channels_header", "📋 Your Channels:") + "\n\n" + description_line
        keyboard = get_channels_list_keyboard(channels, lang)
    success = await message_manager.edit_system(
        callback.message.chat.id,
        text,
        reply_markup=keyboard,
        tag="menu"
    )
    if not success:
        await message_manager.send_system(
            callback.message.chat.id,
            text,
            reply_markup=keyboard,
            tag="menu"
        )


def _channel_detail_text(detail: dict, texts: dict) -> str:
    """Build channel detail system message text (blockquote + stats + description if any)."""
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
    """Send or edit channel detail (with avatar if available). Keeps avatar when toggling mailing."""
    avatar_file_id = detail.get("avatar_telegram_file_id")
    has_avatar = detail.get("has_avatar", False)
    channel_id = detail.get("id")
    if avatar_file_id:
        await message_manager.send_system(
            chat_id,
            text,
            reply_markup=keyboard,
            tag=tag,
            photo=avatar_file_id,
        )
    elif has_avatar and channel_id:
        avatar_bytes = await api.get_channel_avatar_bytes(channel_id)
        if avatar_bytes:
            await message_manager.send_system(
                chat_id,
                text,
                reply_markup=keyboard,
                tag=tag,
                photo_bytes=avatar_bytes,
                photo_filename="avatar.jpg",
            )
            return
    success = await message_manager.edit_system(chat_id, text, reply_markup=keyboard, tag=tag)
    if not success:
        await message_manager.send_system(chat_id, text, reply_markup=keyboard, tag=tag)


@router.callback_query(F.data.startswith("channel_detail:"))
async def on_channel_detail(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Open channel detail (system message): stats, avatar if any, actions."""
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
        callback.message.chat.id,
        detail,
        text,
        keyboard,
        message_manager,
        api,
    )


@router.callback_query(F.data.startswith("channel_mailing_toggle:"))
async def on_channel_mailing_toggle(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Toggle mailing_enabled and refresh channel detail message."""
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
        callback.message.chat.id,
        detail,
        text,
        keyboard,
        message_manager,
        api,
    )


@router.callback_query(F.data.startswith("channel_delete:"))
async def on_channel_delete_confirm(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show temporary confirm for removing channel (Yes/No in one row)."""
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
async def on_channel_delete_do(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Remove channel from user and return to channels list."""
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
    channels = await api.get_user_channels_with_meta(user_id)
    user_data = await api.get_user(user_id)
    has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
    limit = _bonus_channel_limit(user_data)
    bonus_count = (user_data or {}).get("bonus_channels_count", 0)
    slots_left = max(0, limit - bonus_count)
    desc_tpl = texts.get("your_channels_description", "You can add {count} more channel(s).")
    description_line = "<blockquote>" + desc_tpl.format(count=slots_left) + "</blockquote>"
    if not channels:
        text = texts.get("no_user_channels", "You have no channels yet.") + "\n\n" + description_line
        from bot.core import get_channels_view_keyboard
        keyboard = get_channels_view_keyboard(lang, has_bonus_channel=has_bonus)
    else:
        text = texts.get("your_channels_header", "📋 Your Channels:") + "\n\n" + description_line
        keyboard = get_channels_list_keyboard(channels, lang)
    await message_manager.edit_system(
        callback.message.chat.id,
        text,
        reply_markup=keyboard,
        tag="menu"
    )


@router.callback_query(F.data == "back_to_settings")
async def on_back_to_settings(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Go back to settings menu."""
    await message_manager.send_toast(callback)
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    # Use edit_system to ensure temporary messages are deleted
    success = await message_manager.edit_system(
        callback.message.chat.id,
        texts.get("settings_title"),
        reply_markup=get_settings_keyboard(lang),
        tag="menu"
    )
    if not success:
        # Fallback to send_system if edit fails
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("settings_title"),
            reply_markup=get_settings_keyboard(lang),
            tag="menu"
        )


@router.callback_query(F.data == "back_to_feed")
async def on_back_to_feed(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Go back to feed menu."""
    await message_manager.send_toast(callback)

    api = get_core_api()
    user_id = callback.from_user.id
    feed_eligible = await api.get_feed_eligible(user_id)
    if not (feed_eligible and feed_eligible.get("eligible")):
        lang = await _get_user_lang(user_id)
        texts = get_texts(lang)
        from bot.core.keyboards import get_start_keyboard
        success = await message_manager.edit_system(
            callback.message.chat.id,
            texts.get("feed_complete_training_first", "Complete training first to unlock your feed and mailing."),
            reply_markup=get_start_keyboard(lang),
            tag="menu"
        )
        if not success:
            await message_manager.send_system(
                callback.message.chat.id,
                texts.get("feed_complete_training_first", "Complete training first to unlock your feed and mailing."),
                reply_markup=get_start_keyboard(lang),
                tag="menu"
            )
        return
    user_data = await api.get_user(user_id)
    has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
    channels = await api.get_user_channels_with_meta(user_id)
    mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    success = await message_manager.edit_system(
        callback.message.chat.id,
        texts.get("feed_ready"),
        reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
        tag="menu"
    )
    if not success:
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
            tag="menu"
        )


@router.callback_query(F.data == "cancel")
async def on_cancel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Cancel current operation - return to appropriate screen based on user status."""
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
        feed_eligible = await api.get_feed_eligible(user_id)
        if not (feed_eligible and feed_eligible.get("eligible")):
            from bot.core.keyboards import get_start_keyboard
            success = await message_manager.edit_system(
                callback.message.chat.id,
                texts.get("feed_complete_training_first", "Complete training first to unlock your feed and mailing."),
                reply_markup=get_start_keyboard(lang),
                tag="menu"
            )
            if not success:
                await message_manager.send_system(
                    callback.message.chat.id,
                    texts.get("feed_complete_training_first", "Complete training first to unlock your feed and mailing."),
                    reply_markup=get_start_keyboard(lang),
                    tag="menu"
                )
        else:
            has_bonus = user_data.get("bonus_channels_count", 0) >= 1
            channels = await api.get_user_channels_with_meta(user_id)
            mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
            success = await message_manager.edit_system(
                callback.message.chat.id,
                texts.get("feed_ready"),
                reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
                tag="menu"
            )
            if not success:
                await message_manager.send_system(
                    callback.message.chat.id,
                    texts.get("feed_ready"),
                    reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
                    tag="menu"
                )
    elif current_state and "training" in str(current_state).lower():
        from bot.core.keyboards import get_onboarding_keyboard
        success = await message_manager.edit_system(
            callback.message.chat.id,
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang),
            tag="menu"
        )
        if not success:
            await message_manager.send_system(
                callback.message.chat.id,
                texts.get("training_intro"),
                reply_markup=get_onboarding_keyboard(lang),
                tag="menu"
            )
    elif current_state and "adding" in str(current_state).lower():
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
        if user_data and user_data.get("user_role") in ("member", "admin"):
            feed_eligible = await api.get_feed_eligible(user_id)
            if not (feed_eligible and feed_eligible.get("eligible")):
                from bot.core.keyboards import get_start_keyboard
                success = await message_manager.edit_system(
                    callback.message.chat.id,
                    texts.get("feed_complete_training_first", "Complete training first to unlock your feed and mailing."),
                    reply_markup=get_start_keyboard(lang),
                    tag="menu"
                )
                if not success:
                    await message_manager.send_system(
                        callback.message.chat.id,
                        texts.get("feed_complete_training_first", "Complete training first to unlock your feed and mailing."),
                        reply_markup=get_start_keyboard(lang),
                        tag="menu"
                    )
            else:
                channels = await api.get_user_channels_with_meta(user_id)
                mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
                success = await message_manager.edit_system(
                    callback.message.chat.id,
                    texts.get("feed_ready"),
                    reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
                    tag="menu"
                )
                if not success:
                    await message_manager.send_system(
                        callback.message.chat.id,
                        texts.get("feed_ready"),
                        reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
                        tag="menu"
                    )
        else:
            from bot.core.keyboards import get_onboarding_keyboard
            success = await message_manager.edit_system(
                callback.message.chat.id,
                texts.get("training_intro"),
                reply_markup=get_onboarding_keyboard(lang),
                tag="menu"
            )
            if not success:
                await message_manager.send_system(
                    callback.message.chat.id,
                    texts.get("training_intro"),
                    reply_markup=get_onboarding_keyboard(lang),
                    tag="menu"
                )
    else:
        from bot.core import get_start_keyboard
        name = html.escape(callback.from_user.first_name or "there")
        success = await message_manager.edit_system(
            callback.message.chat.id,
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
            tag="menu"
        )
        if not success:
            await message_manager.send_system(
                callback.message.chat.id,
                texts.get("welcome", name=name),
                reply_markup=get_start_keyboard(lang),
                tag="menu"
            )

