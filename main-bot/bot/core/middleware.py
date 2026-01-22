"""Middleware for bot handlers."""

from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.core.message_manager import MessageManager


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

