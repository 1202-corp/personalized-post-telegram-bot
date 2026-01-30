"""Feed action handlers — aggregates bonus, channels, settings, navigation."""

from aiogram import Router

from bot.handlers.feed.bonus import router as bonus_router
from bot.handlers.feed.channels import router as channels_router
from bot.handlers.feed.settings import router as settings_router
from bot.handlers.feed.navigation import router as navigation_router

router = Router()
router.include_router(bonus_router)
router.include_router(channels_router)
router.include_router(settings_router)
router.include_router(navigation_router)
