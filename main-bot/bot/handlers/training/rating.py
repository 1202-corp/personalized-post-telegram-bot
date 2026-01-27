"""Rating handlers for training flow."""

import logging

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
        await message_manager.send_toast(callback)
        return
    _processed_rate_callbacks.add(callback_key)
    
    if len(_processed_rate_callbacks) > 100:
        _processed_rate_callbacks.clear()
    
    _, action, post_id = callback.data.split(":")
    post_id = int(post_id)
    
    await message_manager.send_toast(
        callback, 
        f"{'👍' if action == 'like' else '👎' if action == 'dislike' else '⏭️'}"
    )
    
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.update_activity(user_id)
    
    if action != "skip":
        await api.create_interaction(user_id, post_id, action)
        await api.create_log(user_id, f"post_{action}", f"post_id={post_id}")

    data = await state.get_data()
    
    # Set reaction on the regular post message
    post_message_id = data.get("current_post_message_id")
    if post_message_id:
        reaction_emoji = "👍" if action == "like" else "👎" if action == "dislike" else "⏭️" if action == "skip" else None
        if reaction_emoji:
            try:
                from aiogram.types import ReactionTypeEmoji
                await message_manager.bot.set_message_reaction(
                    chat_id=callback.message.chat.id,
                    message_id=post_message_id,
                    reaction=[ReactionTypeEmoji(emoji=reaction_emoji)]
                )
            except Exception as e:
                logger.warning(f"Failed to set reaction on post message: {e}")
    
    # Delete temporary message with controls (post content is regular message, stays)
    await message_manager.delete_temporary(callback.message.chat.id, tag="training_post_controls")
    
    new_index = data.get("current_post_index", 0) + 1
    rated_count = data.get("rated_count", 0) + (1 if action != "skip" else 0)
    
    await state.update_data(
        current_post_index=new_index,
        rated_count=rated_count,
        current_post_message_id=None,
    )
    
    await show_training_post(callback.message.chat.id, message_manager, state)


@router.callback_query(F.data == "finish_training")
async def on_finish_training(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Finish training and trigger ML model."""
    await message_manager.send_toast(callback, "🎯 Finishing training...")
    await finish_training_flow(callback.message.chat.id, message_manager, state)

