"""Feed view handlers (viewing posts, interactions)."""

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.core import MessageManager, get_texts, get_feed_keyboard, get_feed_post_keyboard
from bot.services import get_core_api

logger = logging.getLogger(__name__)
router = Router()

# Track processed callbacks to prevent double-click
_processed_feed_callbacks: set = set()


from bot.utils import get_user_lang as _get_user_lang


@router.callback_query(F.data == "view_feed")
async def on_view_feed(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Stub: no pull feed; posts are delivered automatically (push) when there is a new post in a channel."""
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    await api.update_activity(user_id)
    feed_eligible = await api.get_feed_eligible(user_id)
    if not (feed_eligible and feed_eligible.get("eligible")):
        lang = await _get_user_lang(user_id)
        texts = get_texts(lang)
        from bot.core.keyboards import get_start_keyboard
        await message_manager.send_system(
            chat_id,
            texts.get("feed_complete_training_first", "Complete training first to unlock your feed and mailing."),
            reply_markup=get_start_keyboard(lang),
            tag="menu"
        )
        return
    user_data = await api.get_user(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
    channels = await api.get_user_channels_with_meta(user_id)
    mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
    msg = texts.get("feed_posts_push_only", "Posts are delivered automatically when there is a new post in a channel. Use My Channels to manage subscriptions.")
    await message_manager.send_system(
        chat_id,
        msg,
        reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus, mailing_any_on=mailing_any_on),
        tag="menu"
    )


@router.callback_query(F.data.startswith("feed:"))
async def on_feed_interaction(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Handle feed post interactions (like/dislike/skip)."""
    callback_key = f"{callback.from_user.id}:{callback.message.message_id}"
    if callback_key in _processed_feed_callbacks:
        await message_manager.send_toast(callback)
        return
    _processed_feed_callbacks.add(callback_key)
    
    if len(_processed_feed_callbacks) > 100:
        _processed_feed_callbacks.clear()
    
    _, action, post_id = callback.data.split(":")
    post_id = int(post_id)
    
    # Show toast based on action
    if action == "like":
        await message_manager.send_toast(callback, "👍")
    elif action == "dislike":
        await message_manager.send_toast(callback, "👎")
    else:
        await message_manager.send_toast(callback, "⏭")
    
    api = get_core_api()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    
    await api.update_activity(user_id)
    
    # Only create interaction for like/dislike, not skip
    if action != "skip":
        await api.create_interaction(user_id, post_id, action)
        await api.create_log(user_id, f"feed_post_{action}", f"post_id={post_id}")
    
    # Delete the 👆 message with buttons
    try:
        await message_manager.bot.delete_message(chat_id, callback.message.message_id)
    except Exception:
        pass
    
    # Set reaction on the post (message before this one)
    # The post message_id is one less than the buttons message_id
    post_message_id = callback.message.message_id - 1
    if action != "skip":
        try:
            from aiogram.types import ReactionTypeEmoji
            reaction = ReactionTypeEmoji(emoji="👍" if action == "like" else "👎")
            await message_manager.bot.set_message_reaction(
                chat_id=chat_id,
                message_id=post_message_id,
                reaction=[reaction]
            )
        except Exception as e:
            logger.debug(f"Could not set reaction: {e}")

