"""Helper functions for training handlers."""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram.fsm.context import FSMContext

from bot.core import MessageManager, get_texts, get_settings
from bot.core.states import TrainingStates
from bot.services import get_core_api, get_user_bot
from bot.services.media_service import MediaService
from bot.services.nudge_service import NudgeService
import html
from bot.utils import TELEGRAM_CAPTION_LIMIT
from bot.core import (
    get_training_post_keyboard, get_feed_keyboard, get_training_complete_keyboard,
    get_bonus_channel_keyboard,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize services (will be injected via dependency injection in future)
_media_service: MediaService | None = None
_nudge_service: NudgeService | None = None


def _get_media_service() -> MediaService:
    """Get or create media service instance."""
    global _media_service
    if _media_service is None:
        _media_service = MediaService(get_user_bot())
    return _media_service


def _get_nudge_service() -> NudgeService:
    """Get or create nudge service instance."""
    global _nudge_service
    if _nudge_service is None:
        _nudge_service = NudgeService()
    return _nudge_service


async def _get_user_lang(user_id: int) -> str:
    """Get user's language preference."""
    api = get_core_api()
    return await api.get_user_language(user_id)


async def _start_training_session(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
    state: FSMContext,
) -> None:
    """Initialize per-session nudge watcher and show the first training post."""
    # Bump session id to invalidate previous watchers
    session_id = f"{user_id}-{int(datetime.utcnow().timestamp() * 1000)}"
    await state.update_data(
        nudge_session_id=session_id,
    )

    # Get user language for nudge service
    lang = await _get_user_lang(user_id)
    
    # Start nudge watcher using service
    nudge_service = _get_nudge_service()
    await nudge_service.start_training_watcher(
        chat_id, user_id, message_manager, state, session_id, lang
    )
    
    # Start background prefetch of ALL posts while showing first one
    data = await state.get_data()
    posts = data.get("training_posts", [])
    if posts:
        media_service = _get_media_service()
        asyncio.create_task(
            media_service.prefetch_all_posts_media(chat_id, posts)
        )

    await show_training_post(chat_id, message_manager, state)


async def _bonus_channel_nudge_watcher(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
) -> None:
    """Напоминания забрать бонусный канал через 1 мин, 1 час и 1 день."""
    api = get_core_api()
    thresholds = [60, 3600, 24 * 3600]

    for stage, delay in enumerate(thresholds, start=1):
        try:
            await asyncio.sleep(delay)

            user = await api.get_user(user_id)
            if not user:
                break

            if user.get("bonus_channels_count", 0) >= 1:
                break

            lang = await _get_user_lang(user_id)
            texts = get_texts(lang)
            key = f"bonus_nudge_{stage}"
            text = texts.get(key)
            if not text:
                text = "🎁 You still have a free bonus channel to claim."

            await message_manager.send_temporary(
                chat_id,
                text,
                reply_markup=get_bonus_channel_keyboard(lang),
                tag="bonus_nudge",
            )
        except Exception as e:
            logger.error(f"Error in bonus channel nudge watcher for user {user_id}: {e}")
            break


async def show_training_post(chat_id: int, message_manager: MessageManager, state: FSMContext):
    """Display current training post for rating."""
    from aiogram.types import InputMediaPhoto, BufferedInputFile
    
    data = await state.get_data()
    posts = data.get("training_posts", [])
    index = data.get("current_post_index", 0)
    user_id = data.get("user_id")
    
    if index >= len(posts):
        # All posts rated
        await finish_training_flow(chat_id, message_manager, state)
        return
    
    post = posts[index]
    
    # Format post text (escape user content for HTML)
    channel_title = html.escape(post.get("channel_title", "Unknown Channel"))
    full_text_raw = post.get("text") or ""
    post_text = html.escape(full_text_raw)
    channel_username = post.get("channel_username", "").lstrip("@")
    msg_id = post.get("telegram_message_id")
    
    # Get user language for localized texts
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Build post text with hyperlink to original (HTML format)
    text = f"📰 <b>{texts.get('post_label', default='Post')} {index + 1}/{len(posts)}</b>\n"
    if channel_username and msg_id:
        text += f"{texts.get('from_label', default='From')}: <a href=\"https://t.me/{channel_username}/{msg_id}\">{channel_title}</a>\n\n"
    else:
        text += f"{texts.get('from_label', default='From')}: {channel_title}\n\n"
    text += post_text if post_text else "<i>[Media content]</i>"
    caption_fits = len(text) <= TELEGRAM_CAPTION_LIMIT
    sent_with_caption = False
    media_message_ids: list[int] = []

    # First send media if available (photo or video)
    media_type = post.get("media_type")
    if media_type == "photo":
        media_ids_str = post.get("media_file_id") or ""

        media_ids: list[int] = []
        if media_ids_str:
            for part in media_ids_str.split(","):
                part = part.strip()
                if part.isdigit():
                    media_ids.append(int(part))
        else:
            msg_id = post.get("telegram_message_id")
            if isinstance(msg_id, int):
                media_ids.append(msg_id)

        if channel_username and media_ids:
            user_bot = get_user_bot()
            
            # Check cache first for ALL photo types
            media_service = _get_media_service()
            cached_photo = await media_service.get_cached_photo(chat_id, post.get("id", 0))
            cached_photos = await media_service.get_cached_photos(chat_id, post.get("id", 0))
            cached = {"photo": cached_photo, "photos": cached_photos} if cached_photo or cached_photos else None

            if len(media_ids) > 1:
                # Album - check cache or download in parallel
                if cached and cached.get("photos"):
                    photos_data = cached["photos"]
                else:
                    tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    photos_data = [r for r in results if r and not isinstance(r, Exception)]

                media_items: list[InputMediaPhoto] = []
                for i, photo_bytes in enumerate(photos_data):
                    input_file = BufferedInputFile(photo_bytes, filename=f"{media_ids[i] if i < len(media_ids) else i}.jpg")
                    media_items.append(InputMediaPhoto(media=input_file))
                if media_items:
                    msgs = await message_manager.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_items,
                    )
                    media_message_ids.extend(m.message_id for m in msgs)
                    # Send text with buttons separately
                    from aiogram.types import LinkPreviewOptions
                    btn_msg = await message_manager.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="MarkdownV2",
                        reply_markup=get_training_post_keyboard(post.get("id"), lang) if post.get("id") else None,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
                    media_message_ids.append(btn_msg.message_id)
                    sent_with_caption = True
            else:
                # Single photo - use cache or download
                mid = media_ids[0]
                if cached and cached.get("photo"):
                    photo_bytes = cached["photo"]
                else:
                    try:
                        photo_bytes = await user_bot.get_photo(channel_username, mid)
                    except Exception:
                        photo_bytes = None
                if photo_bytes:
                    if caption_fits:
                        await message_manager.delete_temporary(chat_id, tag="training_post")
                        await message_manager.send_temporary(
                            chat_id,
                            text,
                            reply_markup=get_training_post_keyboard(post.get("id"), lang),
                            tag="training_post",
                            photo_bytes=photo_bytes,
                            photo_filename=f"{mid}.jpg",
                        )
                        sent_with_caption = True
                    else:
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        msg = await message_manager.bot.send_photo(
                            chat_id=chat_id,
                            photo=input_file,
                        )
                        media_message_ids.append(msg.message_id)

    elif media_type == "video" and channel_username and msg_id:
        # Handle video posts - skip if video fails to load/send
        user_bot = get_user_bot()
        # Check cache first
        media_service = _get_media_service()
        cached_video = await media_service.get_cached_video(chat_id, post.get("id", 0))
        if cached_video:
            video_bytes = cached_video
        else:
            try:
                video_bytes = await user_bot.get_video(channel_username, msg_id)
            except Exception:
                video_bytes = None
        
        if video_bytes:
            try:
                input_file = BufferedInputFile(video_bytes, filename=f"{msg_id}.mp4")
                if caption_fits:
                    await message_manager.delete_temporary(chat_id, tag="training_post")
                    msg = await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                        caption=text,
                        parse_mode="MarkdownV2",
                        reply_markup=get_training_post_keyboard(post.get("id"), lang),
                    )
                    sent_with_caption = True
                else:
                    msg = await message_manager.bot.send_video(
                        chat_id=chat_id,
                        video=input_file,
                    )
                    media_message_ids.append(msg.message_id)
            except Exception as e:
                # Video send failed (timeout, too large, etc.) - skip to next post
                logger.warning(f"Failed to send video for post {post.get('id')}: {e}")
                new_index = index + 1
                await state.update_data(current_post_index=new_index)
                await show_training_post(chat_id, message_manager, state)
                return
        else:
            # Video failed to download - skip to next post
            logger.warning(f"Failed to download video for post {post.get('id')}, skipping")
            new_index = index + 1
            await state.update_data(current_post_index=new_index)
            await show_training_post(chat_id, message_manager, state)
            return

    # Send text-only ephemeral (will be replaced by next post) when not already sent as caption
    if not sent_with_caption:
        await message_manager.delete_temporary(chat_id, tag="training_post")
        await message_manager.send_temporary(
            chat_id,
            text,
            reply_markup=get_training_post_keyboard(post.get("id"), lang),
            tag="training_post",
            disable_link_preview=True,
        )
    
    # Remember media messages for later cleanup on rating
    await state.update_data(last_media_ids=media_message_ids)
    
    # Update system message with progress
    total = len(posts)
    progress_text = texts.get("training_progress", current=index, total=total)

    await message_manager.send_system(
        chat_id,
        progress_text,
        tag="menu",
    )
    
    # Update activity timestamp AFTER message is sent (for accurate nudge timing)
    await state.update_data(last_activity_ts=datetime.utcnow().timestamp())
    
    # Start background prefetch for next posts
    media_service = _get_media_service()
    asyncio.create_task(
        media_service.prefetch_posts_media(chat_id, posts, index + 1, count=3)
    )


async def finish_training_flow(chat_id: int, message_manager: MessageManager, state: FSMContext):
    """Complete training and update user status."""
    logger.info(f"finish_training_flow called for chat_id={chat_id}")
    api = get_core_api()
    data = await state.get_data()
    
    # Clear training posts from state
    training_posts = data.get("training_posts", [])
    rated_count = data.get("rated_count", 0)
    user_id = data.get("user_id")
    is_bonus_training = bool(data.get("is_bonus_training"))
    is_retrain = bool(data.get("is_retrain"))
    
    # Reset user status from "training" to "active"
    if user_id:
        await api.update_user(user_id, status="active", is_trained=True)
    
    # Clean up all training-related messages
    await message_manager.delete_temporary(chat_id, tag="training_post")
    await message_manager.delete_temporary(chat_id, tag="training_nudge")
    await message_manager.delete_temporary(chat_id, tag="bonus_nudge")
    await message_manager.delete_temporary(chat_id, tag="miniapp_choice")
    
    # Clear media cache for this chat to prevent late posts
    media_service = _get_media_service()
    await media_service.clear_cache(chat_id)

    # Get user language
    lang = await _get_user_lang(user_id) if user_id else "en_US"
    texts = get_texts(lang)

    user_has_bonus = False
    if user_id is not None:
        user_data = await api.get_user(user_id)
        if user_data:
            user_has_bonus = user_data.get("bonus_channels_count", 0) >= 1

        # запустить нуджи по бонус-каналу
        try:
            asyncio.create_task(
                _bonus_channel_nudge_watcher(chat_id, user_id, message_manager)
            )
        except Exception as e:
            logger.error(f"Error starting bonus nudge watcher for user {user_id}: {e}")

        # отправить один лучший пост через минуту после обучения
        async def delayed_best_post():
            await asyncio.sleep(60)  # Wait 1 minute
            try:
                await send_initial_best_post(chat_id, user_id, message_manager)
            except Exception as e:
                logger.error(f"Error sending initial best post after training for user {user_id}: {e}")
        
        asyncio.create_task(delayed_best_post())

    await state.clear()

    if is_retrain or is_bonus_training or user_has_bonus:
        # After retraining, bonus training, or if bonus already claimed – go straight to feed
        logger.info(f"Sending feed_ready to chat_id={chat_id} (is_retrain={is_retrain}, is_bonus={is_bonus_training})")
        await message_manager.send_system(
            chat_id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=user_has_bonus),
            tag="menu",
        )
    else:
        logger.info(f"Sending training_complete to chat_id={chat_id}, rated_count={rated_count}")
        await message_manager.send_system(
            chat_id,
            texts.get("training_complete", rated_count=rated_count),
            reply_markup=get_training_complete_keyboard(lang),
            tag="menu",
        )
    logger.info(f"finish_training_flow completed for chat_id={chat_id}")


async def send_initial_best_post(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
) -> None:
    """Train ML model and send a single best recent post once after training.

    Uses the same best-post logic as the feed, but triggers immediately after training
    to show the user value without requiring extra button presses.
    """
    from aiogram.types import InputMediaPhoto, BufferedInputFile, LinkPreviewOptions
    
    api = get_core_api()
    user_bot = get_user_bot()

    await api.update_activity(user_id)
    user_data = await api.get_user(user_id)
    if not user_data:
        return

    # Don't send posts if user is in training mode
    if user_data.get("status") == "training":
        return

    if user_data.get("initial_best_post_sent", False):
        # Already sent once, do not spam
        return

    # Train ML model (mock) so relevance scores are available
    result = await api.train_model(user_id)
    if not result or not result.get("success"):
        logger.warning(
            "ML training after initial training failed for user %s: %s",
            user_id,
            (result or {}).get("message"),
        )

    all_posts = await api.get_best_posts(user_id, limit=10)
    if not all_posts:
        return

    now = datetime.utcnow()
    three_days_ago = now - timedelta(days=3)

    initial_best_post = None
    for post in all_posts:
        posted_at_raw = post.get("posted_at")
        try:
            posted_at = datetime.fromisoformat(posted_at_raw) if posted_at_raw else None
        except Exception:
            posted_at = None
        if posted_at and posted_at >= three_days_ago:
            initial_best_post = post
            break

    if not initial_best_post:
        initial_best_post = all_posts[0]

    # Send this post similarly to feed posts (with rating buttons)
    channel_title = html.escape(initial_best_post.get("channel_title", "Unknown"))
    channel_username = (initial_best_post.get("channel_username") or "").lstrip("@")
    msg_id = initial_best_post.get("telegram_message_id")
    full_text_raw = initial_best_post.get("text") or ""
    text = html.escape(full_text_raw)
    score = initial_best_post.get("relevance_score", 0)

    # Build header with link to original post (HTML format)
    if channel_username and msg_id:
        header = f"📰 <a href=\"https://t.me/{channel_username}/{msg_id}\">{channel_title}</a>\n\n"
    else:
        header = f"📰 <b>{channel_title}</b>\n\n"
    body = text if text else "<i>[Media content]</i>"
    post_text = header + body

    caption_fits = len(post_text) <= TELEGRAM_CAPTION_LIMIT
    sent_with_caption = False

    if initial_best_post.get("media_type") == "photo":
        channel_username = initial_best_post.get("channel_username")
        media_ids_str = initial_best_post.get("media_file_id") or ""

        media_ids: list[int] = []
        if media_ids_str:
            for part in media_ids_str.split(","):
                part = part.strip()
                if part.isdigit():
                    media_ids.append(int(part))
        else:
            msg_id = initial_best_post.get("telegram_message_id")
            if isinstance(msg_id, int):
                media_ids.append(msg_id)

        if channel_username and media_ids:
            if len(media_ids) > 1:
                # Download all photos in parallel
                tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                media_items: list[InputMediaPhoto] = []
                for mid, photo_bytes in zip(media_ids, results):
                    if isinstance(photo_bytes, Exception) or not photo_bytes:
                        continue
                    input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                    media_items.append(InputMediaPhoto(media=input_file))
                if media_items:
                    await message_manager.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_items,
                    )
                    # Send text with buttons separately
                    await message_manager.bot.send_message(
                        chat_id=chat_id,
                        text=post_text,
                        parse_mode="HTML",
                        reply_markup=get_feed_post_keyboard(initial_best_post.get("id")) if initial_best_post.get("id") else None,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
                    sent_with_caption = True
            else:
                mid = media_ids[0]
                try:
                    photo_bytes = await user_bot.get_photo(channel_username, mid)
                except Exception:
                    photo_bytes = None
                if photo_bytes:
                    from bot.core import get_feed_post_keyboard
                    if caption_fits:
                        await message_manager.send_regular(
                            chat_id,
                            post_text,
                            reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
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

    # Handle video posts
    if initial_best_post.get("media_type") == "video" and not sent_with_caption:
        channel_username = initial_best_post.get("channel_username")
        msg_id = initial_best_post.get("telegram_message_id")
        if channel_username and msg_id:
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
                        parse_mode="MarkdownV2",
                        reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
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
            parse_mode="MarkdownV2",
            reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    # Mark as sent so we don't send again
    await api.update_user(user_id, initial_best_post_sent=True)

