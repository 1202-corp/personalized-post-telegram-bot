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
        """Mark user message as temporary (ephemeral) before and after handler execution."""
        # Mark user message as temporary BEFORE handler execution
        # This ensures messages are marked even if handler is not found
        if isinstance(event, Message) and event.from_user and not event.from_user.is_bot:
            try:
                from bot.core.message_registry import ManagedMessage, MessageType
                managed = ManagedMessage(
                    message_id=event.message_id,
                    chat_id=event.chat.id,
                    message_type=MessageType.EPHEMERAL,
                    tag="user_message"
                )
                await self.message_manager.registry.register(managed)
                logger.info(f"Marked user message {event.message_id} (chat {event.chat.id}) as temporary")
            except Exception as e:
                logger.error(f"Could not mark user message {event.message_id} as temporary: {e}", exc_info=True)
        
        # Execute handler (if found)
        if handler:
            result = await handler(event, data)
        else:
            result = None
        
        return result

