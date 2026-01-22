"""Rating handlers for training flow."""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.core import MessageManager
from bot.services import get_core_api
from .helpers import _get_user_lang, show_training_post, finish_training_flow

logger = logging.getLogger(__name__)
router = Router()

# Track processed callbacks to prevent double-click
_processed_rate_callbacks: set = set()


@router.callback_query(F.data.startswith("rate:"))
async def on_rate_post(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle post rating (like/dislike/skip)."""
    callback_key = f"{callback.from_user.id}:{callback.message.message_id}"
    if callback_key in _processed_rate_callbacks:
        await callback.answer()
        return
    _processed_rate_callbacks.add(callback_key)
    
    if len(_processed_rate_callbacks) > 100:
        _processed_rate_callbacks.clear()
    
    _, action, post_id = callback.data.split(":")
    post_id = int(post_id)
    
    await callback.answer(f"{'👍' if action == 'like' else '👎' if action == 'dislike' else '⏭️'}")
    
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.update_activity(user_id)
    
    if action != "skip":
        await api.create_interaction(user_id, post_id, action)
        await api.create_log(user_id, f"post_{action}", f"post_id={post_id}")

    await message_manager.delete_ephemeral(callback.message.chat.id, tag="training_nudge")

    data = await state.get_data()
    last_media_ids = data.get("last_media_ids", []) or []
    for mid in last_media_ids:
        try:
            await message_manager.bot.delete_message(callback.message.chat.id, mid)
        except Exception:
            pass
    await message_manager.delete_ephemeral(callback.message.chat.id, tag="training_post")
    
    new_index = data.get("current_post_index", 0) + 1
    rated_count = data.get("rated_count", 0) + (1 if action != "skip" else 0)
    
    await state.update_data(
        current_post_index=new_index,
        rated_count=rated_count,
        last_media_ids=[],
        last_activity_ts=datetime.utcnow().timestamp(),
    )
    
    await show_training_post(callback.message.chat.id, message_manager, state)


@router.callback_query(F.data == "finish_training")
async def on_finish_training(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Finish training and trigger ML model."""
    await callback.answer("🎯 Finishing training...")
    await message_manager.delete_ephemeral(callback.message.chat.id, tag="training_nudge")
    await finish_training_flow(callback.message.chat.id, message_manager, state)

