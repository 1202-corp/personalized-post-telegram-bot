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
    
    # N-логика очереди и буфера взаимодействий
    from random import choice
    from bot.core import get_settings
    settings = get_settings()
    
    training_posts = data.get("training_posts", [])
    queue = data.get("training_queue", [])
    likes_count = int(data.get("likes_count", 0))
    dislikes_count = int(data.get("dislikes_count", 0))
    skips_count = int(data.get("skips_count", 0))
    extra_from_dislike_used = int(data.get("extra_from_dislike_used", 0))
    extra_from_skip_used = int(data.get("extra_from_skip_used", 0))
    interactions_buffer = data.get("interactions_buffer", [])
    
    # Текущий пост - голова очереди
    if not queue:
        # Нет очереди — завершаем обучение
        await finish_training_flow(callback.message.chat.id, message_manager, state)
        return
    
    current_index = queue.pop(0)
    
    if action == "like":
        likes_count += 1
        interactions_buffer.append({"post_id": post_id, "interaction_type": "like"})
    elif action == "dislike":
        dislikes_count += 1
        interactions_buffer.append({"post_id": post_id, "interaction_type": "dislike"})
        if extra_from_dislike_used < settings.training_max_extra_from_dislike:
            # Добавляем случайный новый пост из пула, который ещё не в очереди
            available_indices = [i for i in range(len(training_posts)) if i not in queue and i != current_index]
            if available_indices:
                queue.append(choice(available_indices))
                extra_from_dislike_used += 1
    elif action == "skip":
        skips_count += 1
        if extra_from_skip_used < settings.training_max_extra_from_skip:
            available_indices = [i for i in range(len(training_posts)) if i not in queue and i != current_index]
            if available_indices:
                queue.append(choice(available_indices))
                extra_from_skip_used += 1
    
    # Если очередь опустела — заканчиваем
    if not queue:
        await state.update_data(
            training_queue=queue,
            likes_count=likes_count,
            dislikes_count=dislikes_count,
            skips_count=skips_count,
            extra_from_dislike_used=extra_from_dislike_used,
            extra_from_skip_used=extra_from_skip_used,
            interactions_buffer=interactions_buffer,
            current_post_message_id=None,
        )
        await finish_training_flow(callback.message.chat.id, message_manager, state)
        return
    
    # Обновляем стейт и показываем следующий пост
    await state.update_data(
        training_queue=queue,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
        skips_count=skips_count,
        extra_from_dislike_used=extra_from_dislike_used,
        extra_from_skip_used=extra_from_skip_used,
        interactions_buffer=interactions_buffer,
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

