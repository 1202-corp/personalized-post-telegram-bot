"""
Command handlers (/start, /help, etc.)
"""

import html
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from bot.core import (
    MessageManager, get_texts,
    get_start_keyboard, get_feed_keyboard, get_settings_keyboard,
    get_language_selection_keyboard,
)
from bot.services import get_core_api

logger = logging.getLogger(__name__)
router = Router()


async def get_user_texts(user_id: int):
    """Get TextManager with user's preferred language."""
    api = get_core_api()
    lang = await api.get_user_language(user_id)
    return get_texts(lang)


from bot.utils import get_user_lang as _get_user_lang


@router.message(CommandStart())
async def cmd_start(message: Message, message_manager: MessageManager, state: FSMContext):
    """Handle /start command - Entry point to AARRR funnel."""
    user = message.from_user
    api = get_core_api()
    
    # Get or create user in database first, then log activity
    # Pass Telegram language_code to set initial language based on user's Telegram interface
    user_data = await api.get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,  # Telegram interface language
    )
    
    await api.update_activity(user.id)
    
    if not user_data:
        lang = await api.get_user_language(user.id)
        texts = get_texts(lang)
        await message_manager.send_system(
            message.chat.id,
            texts.get("error_generic"),
            tag="menu",
            is_start=True
        )
        return
    
    # Delete user's /start command message to keep chat clean
    await message_manager.delete_user_message(message)
    
    # Get user's language preference
    lang = await api.get_user_language(user.id)
    texts = get_texts(lang)
    
    status = user_data.get("status", "new")
    user_role = user_data.get("user_role", "guest")
    name = html.escape(user.first_name or "there")
    
    # Пользователь с статусом training нажал /start = сбросил тренировку → new (guest) или active (member/admin)
    if status == "training":
        await state.clear()
        if user_role in ("member", "admin"):
            await api.update_user(user.id, status="active")
        else:
            await api.update_user(user.id, status="new", user_role="guest")
        status = "active" if user_role in ("member", "admin") else "new"
        user_data = await api.get_user(user.id) or user_data
    
    training_complete = user_role in ("member", "admin")
    
    if not training_complete:
        # Гость (guest): ещё не прошёл тренировку или данные были удалены
        # Всегда приводим статус к "new" и сбрасываем роль на guest
        await api.update_user(user.id, status="new", user_role="guest")
        await message_manager.send_system(
            message.chat.id,
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
            tag="menu",
            is_start=True
        )
    else:
        # Member/Admin: всегда показываем меню ленты (нет состояния «недозавершил»)
        if status != "active":
            await api.update_user(user.id, status="active")
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1
        channels = await api.get_user_channels_with_meta(user.id)
        mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
        await message_manager.send_system(
            message.chat.id,
            texts.get("welcome_back", name=name),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
            tag="menu",
            is_start=True
        )


@router.message(Command("help"))
async def cmd_help(message: Message, message_manager: MessageManager):
    """Handle /help command."""
    await get_core_api().update_activity(message.from_user.id)
    
    # Delete user's message
    await message_manager.delete_user_message(message)
    
    lang = await _get_user_lang(message.from_user.id)
    texts = get_texts(lang)
    await message_manager.send_system(
        message.chat.id,
        texts.get("help"),
        tag="menu"
    )


@router.message(Command("status"))
async def cmd_status(message: Message, message_manager: MessageManager):
    """Handle /status command - Show user's current status."""
    api = get_core_api()
    await api.update_activity(message.from_user.id)
    
    # Delete user's message
    await message_manager.delete_user_message(message)
    
    user_data = await api.get_user(message.from_user.id)
    user_id = message.from_user.id
    
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    if not user_data:
        await message_manager.send_system(
            message.chat.id,
            texts.get("error_generic"),
            tag="menu"
        )
        return
    
    trained_display = "✅" if user_data.get("user_role") in ("member", "admin") else "❌"
    status_text = texts.get("status",
        status=user_data.get("status", "unknown"),
        trained=trained_display,
        bonus_channels=user_data.get("bonus_channels_count", 0),
    )
    
    await message_manager.send_system(
        message.chat.id,
        status_text,
        tag="menu"
    )


@router.message(Command("reset"))
async def cmd_reset(message: Message, message_manager: MessageManager):
    """Handle /reset command - Clean up chat messages."""
    # Delete user's message
    await message_manager.delete_user_message(message)
    
    await message_manager.cleanup_chat(
        message.chat.id,
        include_system=True,
        include_regular=False
    )
    
    await message_manager.send_system(
        message.chat.id,
        "🧹 Chat cleaned up! Use /start to begin again.",
        tag="menu"
    )


@router.callback_query(F.data == "delete_account")
async def on_delete_account(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Ask user to confirm account deletion."""
    await message_manager.send_toast(callback)
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    from bot.core import get_confirm_keyboard
    await message_manager.send_temporary(
        callback.message.chat.id,
        texts.get("delete_account_confirm", default="Are you sure you want to delete your account? This cannot be undone."),
        reply_markup=get_confirm_keyboard("delete_account", lang),
        tag="delete_account_confirm"
    )


@router.callback_query(F.data == "confirm:delete_account")
async def on_confirm_delete_account(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Handle confirmed account deletion."""
    api = get_core_api()
    user_id = callback.from_user.id
    await api.delete_user(user_id, hard=False)
    # Clean up temporary messages
    await message_manager.delete_temporary(callback.message.chat.id)
    # Clear chat system messages
    await message_manager.cleanup_chat(callback.message.chat.id, include_system=True, include_regular=False)
    # Show guest /start menu again
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    name = html.escape(callback.from_user.first_name or "there")
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("welcome", name=name),
        reply_markup=get_start_keyboard(lang),
        tag="menu",
        is_start=True
    )


@router.callback_query(F.data == "cancel:delete_account")
async def on_cancel_delete_account(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Cancel account deletion."""
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    await message_manager.send_toast(callback, texts.get("cancelled", default="Cancelled"))
    await message_manager.delete_temporary(callback.message.chat.id, tag="delete_account_confirm")


@router.callback_query(F.data == "cycle_language")
async def on_cycle_language(callback: CallbackQuery, message_manager: MessageManager):
    """Cycle to next language from SUPPORTED_LANGUAGES."""
    from bot.core.keyboards import get_next_language, get_language_flag
    
    api = get_core_api()
    user_id = callback.from_user.id
    
    # Get current language
    current_lang = await _get_user_lang(user_id)
    
    # Get next language cyclically
    next_lang = get_next_language(current_lang)
    
    # Save language preference to database
    await api.set_user_language(user_id, next_lang)
    
    # Get texts in new language
    texts = get_texts(next_lang)
    name = html.escape(callback.from_user.first_name or "there")
    
    # Show toast with language name
    next_flag = get_language_flag(next_lang)
    # Get language name from its own language file
    next_lang_texts = get_texts(next_lang)
    lang_name = next_lang_texts.get(f"lang_name_{next_lang}", next_lang)
    await message_manager.send_toast(callback, f"{next_flag} {lang_name}")
    
    # Update system message
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("welcome", name=name),
        reply_markup=get_start_keyboard(next_lang),
        tag="menu"
    )


@router.callback_query(F.data == "change_language")
async def on_change_language(callback: CallbackQuery, message_manager: MessageManager):
    """Show language selection in temporary message."""
    await message_manager.send_toast(callback)
    
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Send temporary message with language selection
    await message_manager.send_temporary(
        callback.message.chat.id,
        texts.get("language_selection_title", default="🌐 Select language / Выберите язык:"),
        reply_markup=get_language_selection_keyboard(lang),
        tag="language_selection"
    )


@router.callback_query(F.data.startswith("select_language:"))
async def on_select_language(callback: CallbackQuery, message_manager: MessageManager):
    """Handle language selection from temporary message."""
    api = get_core_api()
    user_id = callback.from_user.id
    
    # Extract language from callback data
    selected_lang = callback.data.split(":")[1]
    
    # Save language preference
    await api.set_user_language(user_id, selected_lang)
    
    # Get texts in new language
    texts = get_texts(selected_lang)
    
    # Show toast with language name
    from bot.core.keyboards import get_language_flag
    flag = get_language_flag(selected_lang)
    # Get language name from its own language file
    selected_lang_texts = get_texts(selected_lang)
    lang_name = selected_lang_texts.get(f"lang_name_{selected_lang}", selected_lang)
    await message_manager.send_toast(callback, f"{flag} {lang_name}")
    
    # Delete temporary language selection message
    await message_manager.delete_temporary(callback.message.chat.id, tag="language_selection")
    
    # Update settings menu with new language
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("settings_title"),
        reply_markup=get_settings_keyboard(selected_lang),
        tag="menu"
    )
