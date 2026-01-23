"""
Catch-all handler for unhandled messages.
This router must be registered LAST to catch only messages that weren't handled by other routers.
"""

import logging
from aiogram import Router
from aiogram.types import Message

from bot.core import MessageManager

logger = logging.getLogger(__name__)
router = Router()


@router.message()
async def catch_all_messages(message: Message, message_manager: MessageManager):
    """
    Catch-all handler for all messages that don't match any other handler.
    This ensures all user messages are deleted, even if they don't have a specific handler.
    """
    # Delete user message (middleware will also try, but this ensures it happens)
    if message.from_user and not message.from_user.is_bot:
        await message_manager.delete_user_message(message)
        logger.debug(f"Deleted unhandled user message {message.message_id} from user {message.from_user.id}")

