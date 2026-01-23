"""
Command handlers (/start, /help, etc.)
"""

import html
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from bot.core import (
    MessageManager, get_texts,
    get_start_keyboard, get_feed_keyboard, get_settings_keyboard,
)
from bot.services import get_core_api

logger = logging.getLogger(__name__)
router = Router()


async def get_user_texts(user_id: int):
    """Get TextManager with user's preferred language."""
    api = get_core_api()
    lang = await api.get_user_language(user_id)
    return get_texts(lang)


async def _get_user_lang(user_id: int) -> str:
    """Get user's language preference."""
    api = get_core_api()
    return await api.get_user_language(user_id)


@router.message(CommandStart())
async def cmd_start(message: Message, message_manager: MessageManager):
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
    
    # Log activity
    await api.update_activity(user.id)
    await api.create_log(user.id, "command_start")
    
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
    
    # Check user status and route accordingly
    status = user_data.get("status", "new")
    name = html.escape(user.first_name or "there")
    
    if status in ["new", "onboarding"]:
        # Show onboarding
        await api.update_user(user.id, status="onboarding")
        await message_manager.send_system(
            message.chat.id,
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
            tag="menu",
            is_start=True
        )
    elif status == "training":
        # Resume training
        await message_manager.send_system(
            message.chat.id,
            texts.get("resume_training"),
            reply_markup=get_start_keyboard(lang),
            tag="menu",
            is_start=True
        )
    elif status in ["trained", "active"]:
        # Show main feed
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1
        await message_manager.send_system(
            message.chat.id,
            texts.get("welcome_back", name=name),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus),
            tag="menu",
            is_start=True
        )
    else:
        # Default to onboarding
        await message_manager.send_system(
            message.chat.id,
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
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
    
    status_text = texts.get("status",
        status=user_data.get("status", "unknown"),
        is_trained="✅" if user_data.get("is_trained") else "❌",
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
    lang_names = {
        "en_US": "English",
        "ru_RU": "Русский"
    }
    lang_name = lang_names.get(next_lang, next_lang)
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
    """Show language selection from settings."""
    await message_manager.send_toast(callback)
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇬🇧 English", callback_data="settings_lang_en"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="settings_lang_ru"),
        ],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="settings")],
    ])
    
    await message_manager.send_system(
        callback.message.chat.id,
        "🌐 Select language / Выберите язык:",
        reply_markup=keyboard,
        tag="menu"
    )


@router.callback_query(F.data == "settings_lang_en")
async def on_settings_lang_en(callback: CallbackQuery, message_manager: MessageManager):
    """Switch to English from settings."""
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.set_user_language(user_id, "en_US")
    texts = get_texts("en_US")
    
    await message_manager.send_toast(callback, "Language: English")
    
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("settings_title"),
        reply_markup=get_settings_keyboard("en_US"),
        tag="menu"
    )


@router.callback_query(F.data == "settings_lang_ru")
async def on_settings_lang_ru(callback: CallbackQuery, message_manager: MessageManager):
    """Switch to Russian from settings."""
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.set_user_language(user_id, "ru_RU")
    texts = get_texts("ru_RU")
    
    await message_manager.send_toast(callback, "Язык: русский")
    
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("settings_title"),
        reply_markup=get_settings_keyboard("ru_RU"),
        tag="menu"
    )


@router.message()
async def handle_all_user_messages(message: Message, message_manager: MessageManager):
    """
    Catch-all handler for all user messages.
    Deletes all user messages that are not handled by other handlers.
    
    Note: In aiogram, more specific handlers (with filters) are processed first.
    This handler will only catch messages that:
    - Are not commands (Command handlers process them first)
    - Are not in FSM states (FSM handlers have higher priority)
    - Are not web_app_data (handled by specific handler)
    
    All user messages are considered temporary and should be deleted.
    """
    # Skip if it's a command (already handled by command handlers)
    if message.text and message.text.startswith("/"):
        return
    
    # Delete user's message - all user messages are temporary
    # This will be called for messages not handled by other handlers
    await message_manager.delete_user_message(message)
