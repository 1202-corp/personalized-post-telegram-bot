"""Middleware for bot handlers."""

import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message

from bot.core.message_manager import MessageManager

logger = logging.getLogger(__name__)


class MessageManagerMiddleware(BaseMiddleware):
    """Middleware to inject MessageManager into handlers."""
    
    def __init__(self, message_manager: MessageManager):
        self.message_manager = message_manager
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Inject message_manager into handler data."""
        data["message_manager"] = self.message_manager
        return await handler(event, data)


class AutoDeleteUserMessagesMiddleware(BaseMiddleware):
    """Middleware to automatically delete all user messages after processing."""
    
    def __init__(self, message_manager: MessageManager):
        self.message_manager = message_manager
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Delete user message after handler execution if it's a user message."""
        # Execute handler first
        result = await handler(event, data)
        
        # Check if this is a user message (not from bot)
        if isinstance(event, Message) and event.from_user and not event.from_user.is_bot:
            # Check if message was already deleted (marked on message object)
            if not getattr(event, '_deleted', False):
                # Delete user message
                try:
                    await self.message_manager.delete_user_message(event)
                except Exception as e:
                    logger.debug(f"Could not delete user message {event.message_id}: {e}")
        
        return result

