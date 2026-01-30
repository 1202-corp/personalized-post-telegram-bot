"""Helper functions for training handlers."""

import asyncio
import html
import logging

from aiogram.fsm.context import FSMContext

from bot.core import MessageManager, get_texts, get_training_post_keyboard
from bot.services import get_user_bot, get_post_cache

from bot.utils import get_user_lang as _get_user_lang

from .post_content import (
    get_post_content_for_display,
    send_training_post_content,
    prefetch_post_content,
    get_media_service,
)

logger = logging.getLogger(__name__)


async def show_training_post(
    chat_id: int, message_manager: MessageManager, state: FSMContext
) -> bool:
    """Display current training post for rating.
    
    Sends two messages:
    1. Regular message - post content (text/media) without buttons
    2. Temporary message - progress text + rating buttons
    """
    data = await state.get_data()
    posts = data.get("training_posts", [])
    queue = data.get("training_queue", [])
    user_id = data.get("user_id")
    
    # Get current post index from queue (if using queue) or fallback to current_post_index
    if queue:
        index = queue[0]  # First item in queue is current post
    else:
        index = data.get("current_post_index", 0)
    
    if index >= len(posts):
        return False

    post = posts[index]
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    channel_title = html.escape(post.get("channel_title", "Unknown Channel"))
    channel_username = post.get("channel_username", "").lstrip("@")
    msg_id = post.get("telegram_message_id")
    post_id = post.get("id")

    post_cache = get_post_cache()
    user_bot = get_user_bot()
    content = await get_post_content_for_display(post_id, post, post_cache, user_bot)
    post_text = content["text"]
    cached_media_type = content["media_type"]
    cached_media_data = content["media_data"]
    cached_telegram_file_id = content["telegram_file_id"]

    next_index = None
    if queue and len(queue) > 1:
        next_index = queue[1]
    elif not queue and index + 1 < len(posts):
        next_index = index + 1
    if next_index is not None and next_index < len(posts):
        next_post = posts[next_index]
        next_post_id = next_post.get("id")
        next_channel_username = (next_post.get("channel_username") or "").lstrip("@")
        next_msg_id = next_post.get("telegram_message_id")
        if next_post_id and next_channel_username and next_msg_id:
            next_cached = await post_cache.get_post_content(next_post_id)
            if not next_cached:
                asyncio.create_task(
                    prefetch_post_content(next_post_id, next_channel_username, next_msg_id)
                )

    if channel_username and msg_id:
        text = f'📰 {texts.get("from_label", default="From")}: <a href="https://t.me/{channel_username}/{msg_id}">{channel_title}</a>\n\n'
    else:
        text = f'📰 {texts.get("from_label", default="From")}: {channel_title}\n\n'
    text += post_text if post_text else "<i>[Media content]</i>"

    post_message_id = await send_training_post_content(
        chat_id=chat_id,
        post=post,
        text=text,
        cached_media_type=cached_media_type,
        cached_media_data=cached_media_data,
        cached_telegram_file_id=cached_telegram_file_id,
        message_manager=message_manager,
    )

    # Now send temporary message with progress and buttons
    # Use initial_queue_size for total (saved at start, doesn't change)
    rated_count = data.get("rated_count", 0)
    initial_queue_size = data.get("initial_queue_size", len(queue) if queue else len(posts))
    progress_text = texts.get("training_progress", current=rated_count, total=initial_queue_size)
    await message_manager.send_temporary(
        chat_id,
        progress_text,
        reply_markup=get_training_post_keyboard(post.get("id"), lang),
        tag="training_post_controls",
    )
    
    await state.update_data(
        current_post_message_id=post_message_id,
    )

    media_service = get_media_service()
    asyncio.create_task(
        media_service.prefetch_posts_media(chat_id, posts, index + 1, count=3)
    )
    return True


