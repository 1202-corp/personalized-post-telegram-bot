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
    """Middleware to mark all user messages as temporary (ephemeral)."""
    
    def __init__(self, message_manager: MessageManager):
        self.message_manager = message_manager
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Mark user message as temporary (ephemeral) after handler execution."""
        # Execute handler first
        result = await handler(event, data)
        
        # Check if this is a user message (not from bot)
        if isinstance(event, Message) and event.from_user and not event.from_user.is_bot:
            # Mark user message as temporary (ephemeral) in registry
            # It will be deleted when bot sends system or regular message
            try:
                from bot.core.message_registry import ManagedMessage, MessageType
                managed = ManagedMessage(
                    message_id=event.message_id,
                    chat_id=event.chat.id,
                    message_type=MessageType.EPHEMERAL,
                    tag="user_message"
                )
                await self.message_manager.registry.register(managed)
                logger.debug(f"Marked user message {event.message_id} as temporary")
            except Exception as e:
                logger.debug(f"Could not mark user message {event.message_id} as temporary: {e}")
        
        return result

