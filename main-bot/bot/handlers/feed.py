"""Feed handlers for trained users (viewing posts, bonus channels, etc.)."""

import logging
import asyncio
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InputMediaPhoto, BufferedInputFile, LinkPreviewOptions
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.message_manager import MessageManager
from bot.api_client import get_core_api, get_user_bot
from bot.keyboards import (
    get_feed_keyboard, get_feed_post_keyboard, get_bonus_channel_keyboard,
    get_settings_keyboard, get_training_complete_keyboard, get_cancel_keyboard,
    get_add_channel_keyboard, get_add_bonus_channel_keyboard
)
from bot.texts import TEXTS, get_texts
from bot.utils import escape_md
from . import training as training_handlers


async def _get_user_lang(user_id: int) -> str:
    """Get user's language preference."""
    api = get_core_api()
    return await api.get_user_language(user_id)

logger = logging.getLogger(__name__)
router = Router()
TELEGRAM_CAPTION_LIMIT = 1024


class FeedStates(StatesGroup):
    """FSM states for feed operations."""
    adding_bonus_channel = State()
    adding_channel = State()


@router.callback_query(F.data == "claim_bonus")
async def on_claim_bonus(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show bonus channel claim option."""
    await callback.answer()
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.update_activity(user_id)
    user_data = await api.get_user(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await message_manager.send_ephemeral(
            callback.message.chat.id,
            texts.get("already_have_bonus"),
            auto_delete_after=5.0
        )
        return
    
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("bonus_channel"),
        reply_markup=get_bonus_channel_keyboard(lang),
        tag="menu"
    )


@router.callback_query(F.data == "retrain")
async def on_retrain_model(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start a new interactive retraining session on user's channels."""
    await callback.answer()

    await training_handlers.start_full_retrain(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        message_manager=message_manager,
        state=state,
    )


@router.callback_query(F.data == "add_bonus_channel")
async def on_add_bonus_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Prompt for bonus channel."""
    await callback.answer()
    
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Check if user already has a bonus channel
    user_data = await api.get_user(user_id)
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=True),
            tag="menu"
        )
        return
    
    await state.set_state(FeedStates.adding_bonus_channel)
    
    # Delete any bonus nudge messages to avoid duplicate prompts
    await message_manager.delete_ephemeral(callback.message.chat.id, tag="bonus_nudge")
    
    try:
        await callback.message.edit_text(
            texts.get("add_channel_prompt"),
            reply_markup=get_add_bonus_channel_keyboard(lang)
        )
    except Exception:
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("add_channel_prompt"),
            reply_markup=get_add_bonus_channel_keyboard(lang),
            tag="menu"
        )


@router.message(FeedStates.adding_bonus_channel)
async def on_bonus_channel_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle bonus channel input."""
    channel_input = message.text.strip()
    # Delete user's input message to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = message.from_user.id
    
    await api.update_activity(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Check if user already has a bonus channel
    user_data = await api.get_user(user_id)
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await state.clear()
        await message_manager.send_system(
            message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=True),
            tag="menu"
        )
        return
    
    # Validate and extract username
    if channel_input.startswith("https://t.me/"):
        username = "@" + channel_input.split("/")[-1]
    elif channel_input.startswith("@"):
        username = channel_input
    else:
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("invalid_channel_username"),
            auto_delete_after=5.0
        )
        return
    
    # Show loading
    await message_manager.send_ephemeral(
        message.chat.id,
        texts.get("adding_bonus_channel", username=username),
        tag="loading"
    )
    
    # Try to join channel
    join_result = await user_bot.join_channel(username)
    
    if join_result and join_result.get("success"):
        # Scrape the new channel FIRST (this creates the channel in DB)
        await user_bot.scrape_channel(username, limit=10)
        
        # Ensure user exists before adding channel
        user_obj = message.from_user
        await api.get_or_create_user(
            telegram_id=user_id,
            username=user_obj.username,
            first_name=user_obj.first_name,
            last_name=user_obj.last_name
        )
        
        # Now add as bonus channel (channel exists in DB after scraping)
        add_result = await api.add_user_channel(user_id, username, is_bonus=True)
        if add_result:
            await api.update_user(user_id, bonus_channels_count=1)
            await api.create_log(user_id, "bonus_channel_claimed", username)
        
        await state.clear()
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")

        # Short additional training focused on the bonus channel
        await training_handlers.start_bonus_training(
            chat_id=message.chat.id,
            user_id=user_id,
            username=username,
            message_manager=message_manager,
            state=state,
        )
    else:
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("cannot_access_channel", username=username),
            auto_delete_after=5.0
        )


@router.callback_query(F.data == "skip_bonus")
async def on_skip_bonus(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Skip bonus channel claim."""
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    await callback.answer(texts.get("you_can_claim_later"))
    
    # User skipped bonus, so has_bonus_channel=False
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("feed_ready"),
        reply_markup=get_feed_keyboard(lang, has_bonus_channel=False),
        tag="menu"
    )


@router.callback_query(F.data == "view_feed")
async def on_view_feed(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show the personalized feed."""
    await callback.answer()
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
    
    user_bot = get_user_bot()

    async def _send_single_post(post: dict):
        channel_title = post.get("channel_title", "Unknown")
        channel_username = post.get("channel_username", "").lstrip("@")
        message_id = post.get("telegram_message_id")
        full_text_raw = post.get("text") or ""
        text = escape_md(full_text_raw)
        score = post.get("relevance_score", 0)
        
        # Create hyperlink to original post
        if channel_username and message_id:
            header = f"📰 [{escape_md(channel_title)}](https://t.me/{channel_username}/{message_id})\n\n"
        else:
            header = f"📰 *{escape_md(channel_title)}*\n\n"
        body = text if text else "_[Media content]_"
        post_text = header + body

        caption_fits = len(post_text) <= TELEGRAM_CAPTION_LIMIT
        sent_with_caption = False
        media_type = post.get("media_type")
        channel_username = post.get("channel_username", "").lstrip("@")
        msg_id = post.get("telegram_message_id")

        # Send media if available (photo or video)
        if media_type == "photo":
            media_ids_str = post.get("media_file_id") or ""

            media_ids: list[int] = []
            if media_ids_str:
                for part in media_ids_str.split(","):
                    part = part.strip()
                    if part.isdigit():
                        media_ids.append(int(part))
            else:
                if isinstance(msg_id, int):
                    media_ids.append(msg_id)

            if channel_username and media_ids:
                if len(media_ids) > 1:
                    # Album - send as media group, text will remain separate
                    tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    media_items: list[InputMediaPhoto] = []
                    for mid, res in zip(media_ids, results):
                        if isinstance(res, Exception) or not res:
                            continue
                        photo_bytes = res
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        media_items.append(InputMediaPhoto(media=input_file))
                    if media_items:
                        await message_manager.bot.send_media_group(
                            chat_id=chat_id,
                            media=media_items,
                        )
                else:
                    # Single photo - try to send with caption if it fits
                    mid = media_ids[0]
                    try:
                        photo_bytes = await user_bot.get_photo(channel_username, mid)
                    except Exception:
                        photo_bytes = None
                    if photo_bytes:
                        if caption_fits:
                            await message_manager.send_onetime(
                                chat_id,
                                post_text,
                                reply_markup=get_feed_post_keyboard(post.get("id"), lang),
                                tag="feed_post",
                                photo_bytes=photo_bytes,
                                photo_filename=f"{mid}.jpg",
                            )
                            sent_with_caption = True
                        else:
                            input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                            await message_manager.bot.send_photo(
                                chat_id=chat_id,
                                photo=input_file,
                            )

        elif media_type == "video" and channel_username and msg_id:
            # Handle video posts
            try:
                video_bytes = await user_bot.get_video(channel_username, msg_id)
            except Exception:
                video_bytes = None
            if video_bytes:
                input_file = BufferedInputFile(video_bytes, filename=f"{msg_id}.mp4")
                if caption_fits:
                    await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                        caption=post_text,
                        parse_mode="Markdown",
                        reply_markup=get_feed_post_keyboard(post.get("id"), lang),
                    )
                    sent_with_caption = True
                else:
                    await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                    )

        if not sent_with_caption:
            await message_manager.bot.send_message(
                chat_id=chat_id,
                text=post_text,
                parse_mode="Markdown",
                reply_markup=get_feed_post_keyboard(post.get("id"), lang),
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )

    # Send initial best post once, if applicable
    if initial_best_post:
        await _send_single_post(initial_best_post)
        # Mark as sent so we don't repeat in future sessions
        await api.update_user(user_id, initial_best_post_sent=True)

    # Send remaining feed posts
    for post in feed_posts:
        await _send_single_post(post)


# Track processed callbacks to prevent double-click
_processed_feed_callbacks: set = set()

@router.callback_query(F.data.startswith("feed:"))
async def on_feed_interaction(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Handle feed post interactions (like/dislike)."""
    # Prevent double-click by checking if this callback was already processed
    callback_key = f"{callback.from_user.id}:{callback.message.message_id}"
    if callback_key in _processed_feed_callbacks:
        await callback.answer()
        return
    _processed_feed_callbacks.add(callback_key)
    
    # Clean up old entries (keep only last 100)
    if len(_processed_feed_callbacks) > 100:
        _processed_feed_callbacks.clear()
    
    _, action, post_id = callback.data.split(":")
    post_id = int(post_id)
    
    await callback.answer("👍" if action == "like" else "👎")
    
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


@router.callback_query(F.data == "add_channel_feed")
async def on_add_channel_feed(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Add a new channel from feed menu."""
    await callback.answer()
    
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Check if user already has a bonus channel
    user_data = await api.get_user(user_id)
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=True),
            tag="menu"
        )
        return
    
    await state.set_state(FeedStates.adding_channel)
    
    # Delete any bonus nudge messages to avoid duplicate prompts
    await message_manager.delete_ephemeral(callback.message.chat.id, tag="bonus_nudge")
    
    try:
        await callback.message.edit_text(
            texts.get("add_channel_prompt"),
            reply_markup=get_add_channel_keyboard(lang)
        )
    except Exception:
        # If edit fails, use message_manager which handles cleanup
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("add_channel_prompt"),
            reply_markup=get_add_channel_keyboard(lang),
            tag="menu"
        )


@router.message(FeedStates.adding_channel)
async def on_channel_feed_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle channel input from feed menu - same as bonus channel flow."""
    channel_input = message.text.strip()
    # Delete user's input message to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = message.from_user.id
    
    await api.update_activity(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Check if user already has a bonus channel
    user_data = await api.get_user(user_id)
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await state.clear()
        await message_manager.send_system(
            message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=True),
            tag="menu"
        )
        return
    
    # Validate and extract username
    if channel_input.startswith("https://t.me/"):
        username = "@" + channel_input.split("/")[-1]
    elif channel_input.startswith("@"):
        username = channel_input
    else:
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("invalid_channel_username_short"),
            auto_delete_after=5.0
        )
        return
    
    # Show loading
    await message_manager.send_ephemeral(
        message.chat.id,
        texts.get("adding_bonus_channel", username=username),
        tag="loading"
    )
    
    # Try to join and add channel
    join_result = await user_bot.join_channel(username)
    
    if join_result and join_result.get("success"):
        # Scrape the new channel FIRST (this creates the channel in DB)
        await user_bot.scrape_channel(username, limit=10)
        
        # Ensure user exists before adding channel
        user_obj = message.from_user
        await api.get_or_create_user(
            telegram_id=user_id,
            username=user_obj.username,
            first_name=user_obj.first_name,
            last_name=user_obj.last_name
        )
        
        # Now add as bonus channel (channel exists in DB after scraping)
        add_result = await api.add_user_channel(user_id, username, is_bonus=True)
        if add_result:
            await api.update_user(user_id, bonus_channels_count=1)
            await api.create_log(user_id, "bonus_channel_claimed", username)
        
        await state.clear()
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")
        
        # Start bonus training for this channel
        await training_handlers.start_bonus_training(
            chat_id=message.chat.id,
            user_id=user_id,
            username=username,
            message_manager=message_manager,
            state=state,
        )
    else:
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("cannot_access_channel", username=username),
            auto_delete_after=5.0
        )


@router.callback_query(F.data == "settings")
async def on_settings(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show settings menu."""
    await callback.answer()
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    # Edit current message instead of sending new one
    try:
        await callback.message.edit_text(
            texts.get("settings_title"),
            reply_markup=get_settings_keyboard(lang)
        )
    except Exception:
        pass


@router.callback_query(F.data == "my_channels")
async def on_my_channels(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show user's channels."""
    await callback.answer()
    api = get_core_api()
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    channels = await api.get_user_channels(callback.from_user.id)
    
    if not channels:
        text = texts.get("no_user_channels")
    else:
        text = texts.get("your_channels_header")
        for ch in channels:
            username = escape_md(ch.get("username", "Unknown"))
            title = escape_md(ch.get("title", ""))
            text += f"• @{username} - {title}\n"
    
    from bot.keyboards import get_channels_view_keyboard
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_channels_view_keyboard(lang)
        )
    except Exception:
        pass


@router.callback_query(F.data == "back_to_settings")
async def on_back_to_settings(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Go back to settings menu."""
    await callback.answer()
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("settings_title"),
            reply_markup=get_settings_keyboard(lang)
        )
    except Exception:
        pass


@router.callback_query(F.data == "back_to_feed")
async def on_back_to_feed(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Go back to feed menu."""
    await callback.answer()
    
    api = get_core_api()
    user_data = await api.get_user(callback.from_user.id)
    has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    # Edit current message instead of sending new one
    try:
        await callback.message.edit_text(
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus)
        )
    except Exception:
        pass


@router.callback_query(F.data == "cancel")
async def on_cancel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Cancel current operation - return to appropriate screen based on user status."""
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    await callback.answer(texts.get("cancelled"))
    
    # Get current state before clearing
    current_state = await state.get_state()
    state_data = await state.get_data()
    
    await state.clear()
    
    api = get_core_api()
    user_data = await api.get_user(callback.from_user.id)
    
    # If user is trained, show feed menu
    if user_data and user_data.get("is_trained"):
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1
        try:
            await callback.message.edit_text(
                texts.get("feed_ready"),
                reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus)
            )
        except Exception:
            pass
    # If user was in training (adding channel during training), return to training
    elif current_state and "training" in str(current_state).lower():
        from bot.keyboards import get_training_keyboard
        try:
            await callback.message.edit_text(
                texts.get("training_intro"),
                reply_markup=get_training_keyboard(lang)
            )
        except Exception:
            pass
    # If user was adding bonus channel, show feed with add channel option
    elif current_state and "adding" in str(current_state).lower():
        # User cancelled adding a channel - show feed menu
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
        if user_data and user_data.get("is_trained"):
            try:
                await callback.message.edit_text(
                    texts.get("feed_ready"),
                    reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus)
                )
            except Exception:
                pass
        else:
            from bot.keyboards import get_training_keyboard
            try:
                await callback.message.edit_text(
                    texts.get("training_intro"),
                    reply_markup=get_training_keyboard(lang)
                )
            except Exception:
                pass
    else:
        # Default: show start screen for new users
        from bot.keyboards import get_start_keyboard
        name = escape_md(callback.from_user.first_name or "there")
        try:
            await callback.message.edit_text(
                texts.get("welcome", name=name),
                reply_markup=get_start_keyboard(lang)
            )
        except Exception:
            pass
