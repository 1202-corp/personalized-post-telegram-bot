"""Feed handlers module."""

from bot.handlers.feed.view import router as view_router
from bot.handlers.feed.actions import router as actions_router

# Combine all routers
router = view_router
router.include_router(actions_router)

__all__ = ["router"]

