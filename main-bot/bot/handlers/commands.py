"""
Command handlers (/start, /help, etc.)
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from bot.message_manager import MessageManager
from bot.api_client import get_core_api
from bot.keyboards import get_start_keyboard, get_feed_keyboard, get_settings_keyboard
from bot.texts import TEXTS, get_texts
from bot.utils import escape_md

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
    user_data = await api.get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    
    # Log activity
    await api.update_activity(user.id)
    await api.create_log(user.id, "command_start")
    
    if not user_data:
        lang = await api.get_user_language(user.id)
        texts = get_texts(lang)
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("error_generic"),
            auto_delete_after=5.0
        )
        return
    
    # Delete user's /start command message to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass
    
    # Get user's language preference
    lang = await api.get_user_language(user.id)
    texts = get_texts(lang)
    
    # Check user status and route accordingly
    status = user_data.get("status", "new")
    name = escape_md(user.first_name or "there")
    
    if status in ["new", "onboarding"]:
        # Show onboarding
        await api.update_user(user.id, status="onboarding")
        await message_manager.send_system(
            message.chat.id,
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
            tag="menu"
        )
    elif status == "training":
        # Resume training
        await message_manager.send_system(
            message.chat.id,
            texts.get("resume_training"),
            reply_markup=get_start_keyboard(lang),
            tag="menu"
        )
    elif status in ["trained", "active"]:
        # Show main feed
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1
        await message_manager.send_system(
            message.chat.id,
            texts.get("welcome_back", name=name),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus),
            tag="menu"
        )
    else:
        # Default to onboarding
        await message_manager.send_system(
            message.chat.id,
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
            tag="menu"
        )


@router.message(Command("help"))
async def cmd_help(message: Message, message_manager: MessageManager):
    """Handle /help command."""
    await get_core_api().update_activity(message.from_user.id)
    
    lang = await _get_user_lang(message.from_user.id)
    texts = get_texts(lang)
    await message_manager.send_ephemeral(
        message.chat.id,
        texts.get("help"),
        auto_delete_after=30.0
    )


@router.message(Command("status"))
async def cmd_status(message: Message, message_manager: MessageManager):
    """Handle /status command - Show user's current status."""
    api = get_core_api()
    await api.update_activity(message.from_user.id)
    
    user_data = await api.get_user(message.from_user.id)
    user_id = message.from_user.id
    
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    if not user_data:
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("error_generic"),
            auto_delete_after=5.0
        )
        return
    
    status_text = texts.get("status",
        status=user_data.get("status", "unknown"),
        is_trained="✅" if user_data.get("is_trained") else "❌",
        bonus_channels=user_data.get("bonus_channels_count", 0),
    )
    
    await message_manager.send_ephemeral(
        message.chat.id,
        status_text,
        auto_delete_after=15.0
    )


@router.message(Command("reset"))
async def cmd_reset(message: Message, message_manager: MessageManager):
    """Handle /reset command - Clean up chat messages."""
    await message_manager.cleanup_chat(
        message.chat.id,
        include_system=True,
        include_onetime=False
    )
    
    await message_manager.send_ephemeral(
        message.chat.id,
        "🧹 Chat cleaned up! Use /start to begin again.",
        auto_delete_after=5.0
    )


@router.callback_query(F.data == "set_lang_en")
async def on_set_lang_en(callback: CallbackQuery, message_manager: MessageManager):
    """Switch bot language to English and show updated start menu."""
    api = get_core_api()
    user_id = callback.from_user.id
    
    # Save language preference to database
    await api.set_user_language(user_id, "en")
    
    # Get texts in new language
    texts = get_texts("en")
    name = escape_md(callback.from_user.first_name or "there")
    
    await callback.answer("Language: English")
    
    # Edit current message instead of sending new one
    try:
        await callback.message.edit_text(
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard("en")
        )
    except Exception:
        pass


@router.callback_query(F.data == "set_lang_ru")
async def on_set_lang_ru(callback: CallbackQuery, message_manager: MessageManager):
    """Switch bot language to Russian and show updated start menu."""
    api = get_core_api()
    user_id = callback.from_user.id
    
    # Save language preference to database
    await api.set_user_language(user_id, "ru")
    
    # Get texts in new language
    texts = get_texts("ru")
    name = escape_md(callback.from_user.first_name or "there")
    
    await callback.answer("Язык: русский")
    
    # Edit current message instead of sending new one
    try:
        await callback.message.edit_text(
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard("ru")
        )
    except Exception:
        pass


@router.callback_query(F.data == "change_language")
async def on_change_language(callback: CallbackQuery, message_manager: MessageManager):
    """Show language selection from settings."""
    await callback.answer()
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇬🇧 English", callback_data="settings_lang_en"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="settings_lang_ru"),
        ],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="settings")],
    ])
    
    try:
        await callback.message.edit_text(
            "🌐 Select language / Выберите язык:",
            reply_markup=keyboard
        )
    except Exception:
        pass


@router.callback_query(F.data == "settings_lang_en")
async def on_settings_lang_en(callback: CallbackQuery, message_manager: MessageManager):
    """Switch to English from settings."""
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.set_user_language(user_id, "en")
    texts = get_texts("en")
    
    await callback.answer("Language: English")
    
    try:
        await callback.message.edit_text(
            texts.get("settings_title"),
            reply_markup=get_settings_keyboard("en")
        )
    except Exception:
        pass


@router.callback_query(F.data == "settings_lang_ru")
async def on_settings_lang_ru(callback: CallbackQuery, message_manager: MessageManager):
    """Switch to Russian from settings."""
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.set_user_language(user_id, "ru")
    texts = get_texts("ru")
    
    await callback.answer("Язык: русский")
    
    try:
        await callback.message.edit_text(
            texts.get("settings_title"),
            reply_markup=get_settings_keyboard("ru")
        )
    except Exception:
        pass
