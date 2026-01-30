"""Shared helpers for feed handlers."""

from typing import Optional, Tuple
from aiogram.types import InlineKeyboardMarkup

from bot.core import MessageManager, get_texts
from bot.core.config import get_settings


def bonus_channel_limit(user_data: Optional[dict]) -> int:
    """Return max bonus channels from config: admin or member limit."""
    s = get_settings()
    if user_data and user_data.get("user_role") == "admin":
        return s.bonus_channel_limit_admin
    return s.bonus_channel_limit_member


async def show_menu(
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    message_manager: MessageManager,
    tag: str = "menu",
) -> None:
    """Edit system message or send new if edit fails (e.g. flood control)."""
    success = await message_manager.edit_system(chat_id, text, reply_markup=reply_markup, tag=tag)
    if not success:
        await message_manager.send_system(chat_id, text, reply_markup=reply_markup, tag=tag)
