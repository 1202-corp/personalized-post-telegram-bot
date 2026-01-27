"""Feed view handlers (viewing posts, interactions)."""

import logging
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.core import MessageManager, get_texts, get_feed_keyboard, get_feed_post_keyboard
from bot.services import get_core_api, get_user_bot
from bot.services.media_service import MediaService
from bot.services.post_service import PostService
import html

logger = logging.getLogger(__name__)
router = Router()

# Track processed callbacks to prevent double-click
_processed_feed_callbacks: set = set()


async def _get_user_lang(user_id: int) -> str:
    """Get user's language preference."""
    api = get_core_api()
    return await api.get_user_language(user_id)


@router.callback_query(F.data == "view_feed")
async def on_view_feed(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show the personalized feed."""
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    await api.update_activity(user_id)
    await api.update_user(user_id, status="active")

    user_data = await api.get_user(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)

    # Fetch a larger pool of best posts for initial highlight and regular feed
    all_posts = await api.get_best_posts(user_id, limit=10)
    
    if not all_posts:
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
        await message_manager.send_system(
            chat_id,
            texts.get("feed_empty"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus),
            tag="menu"
        )
        return
    
    # Determine if we should send the one-time initial best post
    initial_best_post = None
    if user_data and not user_data.get("initial_best_post_sent", False):
        now = datetime.utcnow()
        three_days_ago = now - timedelta(days=3)

        for post in all_posts:
            posted_at_raw = post.get("posted_at")
            try:
                posted_at = datetime.fromisoformat(posted_at_raw) if posted_at_raw else None
            except Exception:
                posted_at = None
            if posted_at and posted_at >= three_days_ago:
                initial_best_post = post
                break

        # Fallback: if nothing in last 3 days, take the first best post
        if not initial_best_post:
            initial_best_post = all_posts[0]

    # Build list of feed posts (exclude initial best to avoid duplicates)
    feed_posts = []
    used_initial_id = initial_best_post.get("id") if initial_best_post else None
    for post in all_posts:
        if used_initial_id is not None and post.get("id") == used_initial_id:
            continue
        feed_posts.append(post)
        if len(feed_posts) >= 3:
            break

    total_count = len(feed_posts) + (1 if initial_best_post else 0)

    # Show feed menu
    has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
    await message_manager.send_system(
        chat_id,
        f"📰 {texts.get('feed_ready', default='Your Personalized Feed')} ({total_count})",
        reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus),
        tag="menu"
    )
    
    # Initialize services
    user_bot = get_user_bot()
    media_service = MediaService(user_bot)
    post_service = PostService(message_manager, media_service, user_bot)

    # Send initial best post once, if applicable
    if initial_best_post:
        # Format post text with hyperlink (HTML)
        channel_title = html.escape(initial_best_post.get("channel_title", "Unknown"))
        channel_username = initial_best_post.get("channel_username", "").lstrip("@")
        message_id = initial_best_post.get("telegram_message_id")
        full_text_raw = initial_best_post.get("text") or ""
        text = full_text_raw  # Already HTML formatted from user-bot
        
        if channel_username and message_id:
            header = f"📰 <a href=\"https://t.me/{channel_username}/{message_id}\">{channel_title}</a>\n\n"
        else:
            header = f"📰 <b>{channel_title}</b>\n\n"
        body = text if text else "<i>[Media content]</i>"
        post_text = header + body
        
        # Update post dict with formatted text for post_service
        formatted_post = initial_best_post.copy()
        formatted_post["text"] = post_text
        
        await post_service.send_post(
            chat_id,
            formatted_post,
            keyboard=get_feed_post_keyboard(initial_best_post.get("id"), lang) if initial_best_post.get("id") else None,
            tag="feed_post",
            message_type="regular",
            include_relevance=True,
        )
        # Mark as sent so we don't repeat in future sessions
        await api.update_user(user_id, initial_best_post_sent=True)

    # Send remaining feed posts
    for post in feed_posts:
        # Format post text with hyperlink (HTML)
        channel_title = html.escape(post.get("channel_title", "Unknown"))
        channel_username = post.get("channel_username", "").lstrip("@")
        message_id = post.get("telegram_message_id")
        full_text_raw = post.get("text") or ""
        text = full_text_raw  # Already HTML formatted from user-bot
        
        if channel_username and message_id:
            header = f"📰 <a href=\"https://t.me/{channel_username}/{message_id}\">{channel_title}</a>\n\n"
        else:
            header = f"📰 <b>{channel_title}</b>\n\n"
        body = text if text else "<i>[Media content]</i>"
        post_text = header + body
        
        # Update post dict with formatted text for post_service
        formatted_post = post.copy()
        formatted_post["text"] = post_text
        
        await post_service.send_post(
            chat_id,
            formatted_post,
            keyboard=get_feed_post_keyboard(post.get("id"), lang) if post.get("id") else None,
            tag="feed_post",
            message_type="regular",
            include_relevance=True,
        )


@router.callback_query(F.data.startswith("feed:"))
async def on_feed_interaction(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Handle feed post interactions (like/dislike)."""
    callback_key = f"{callback.from_user.id}:{callback.message.message_id}"
    if callback_key in _processed_feed_callbacks:
        await message_manager.send_toast(callback)
        return
    _processed_feed_callbacks.add(callback_key)
    
    if len(_processed_feed_callbacks) > 100:
        _processed_feed_callbacks.clear()
    
    _, action, post_id = callback.data.split(":")
    post_id = int(post_id)
    
    await message_manager.send_toast(callback, "👍" if action == "like" else "👎")
    
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.update_activity(user_id)
    await api.create_interaction(user_id, post_id, action)
    await api.create_log(user_id, f"feed_post_{action}", f"post_id={post_id}")
    
    # Update button to show it was rated
    await message_manager.edit_reply_markup(
        callback.message.chat.id,
        callback.message.message_id,
        reply_markup=None  # Remove buttons after rating
    )

