"""Service modules for the bot."""

from bot.services.api_service import (
    CoreAPIClient,
    UserBotClient,
    get_core_api,
    get_user_bot,
    close_clients,
)

__all__ = [
    "CoreAPIClient",
    "UserBotClient",
    "get_core_api",
    "get_user_bot",
    "close_clients",
]

