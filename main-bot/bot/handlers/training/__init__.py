"""Training handlers module."""

from bot.handlers.training.onboarding import router as onboarding_router
from bot.handlers.training.rating import router as rating_router
from bot.handlers.training.retrain import router as retrain_router, start_full_retrain, start_bonus_training
from bot.handlers.training.helpers import (
    _start_training_session,
    _bonus_channel_nudge_watcher,
    send_initial_best_post,
    finish_training_flow,
    show_training_post,
)

# Combine all routers
router = onboarding_router
router.include_router(rating_router)
router.include_router(retrain_router)

__all__ = [
    "router",
    "start_full_retrain",
    "start_bonus_training",
    "_start_training_session",
    "_bonus_channel_nudge_watcher",
    "send_initial_best_post",
    "finish_training_flow",
    "show_training_post",
]

