"""Training flow: session start, completion, and initial best post."""

import asyncio
import html
import logging
from typing import Optional, List

from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.types import InputMediaPhoto, BufferedInputFile, LinkPreviewOptions

from bot.core import MessageManager, get_texts, get_feed_keyboard, get_feed_post_keyboard
from bot.services import get_core_api, get_user_bot, get_post_cache

from .helpers import _get_user_lang, show_training_post
from .post_content import ensure_first_posts_cached, get_media_service

logger = logging.getLogger(__name__)


async def _start_training_session(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
    state: FSMContext,
) -> None:
    """Initialize and show the first training post."""
    data = await state.get_data()
    posts = data.get("training_posts", [])
    await ensure_first_posts_cached(posts)
    showed = await show_training_post(chat_id, message_manager, state)
    if not showed:
        await finish_training_flow(chat_id, message_manager, state)


async def _bonus_channel_nudge_watcher(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
) -> None:
    """Напоминания забрать бонусный канал через 1 мин, 1 час и 1 день."""
    from bot.core import get_bonus_channel_keyboard

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
            logger.error("Error in bonus channel nudge watcher for user %s: %s", user_id, e)
            break


async def finish_training_flow(
    chat_id: int, message_manager: MessageManager, state: FSMContext
) -> None:
    """Complete training and update user status."""
    logger.info("finish_training_flow called for chat_id=%s", chat_id)
    api = get_core_api()
    data = await state.get_data()

    training_posts = data.get("training_posts", [])
    user_id = data.get("user_id")

    if user_id:
        await api.mark_training_complete(user_id, skip_notify=True)
        exclude_post_ids = [p.get("id") for p in training_posts if p.get("id") is not None]

        async def train_then_best_post():
            try:
                result = await api.train_model(user_id)
                if not (result and result.get("success")):
                    logger.warning(
                        "ML train after training complete failed for user %s: %s",
                        user_id,
                        (result or {}).get("message"),
                    )
                await send_initial_best_post(
                    chat_id, user_id, message_manager, exclude_post_ids, ml_already_trained=True
                )
            except Exception as e:
                logger.error(
                    "Train or best post after training complete for user %s: %s", user_id, e
                )

        asyncio.create_task(train_then_best_post())

    await message_manager.delete_temporary(chat_id, tag="training_post_controls")
    await message_manager.delete_temporary(chat_id, tag="bonus_nudge")
    await message_manager.delete_temporary(chat_id, tag="miniapp_choice")

    media_service = get_media_service()
    await media_service.clear_cache(chat_id)

    lang = await _get_user_lang(user_id) if user_id else "en_US"
    texts = get_texts(lang)

    user_has_bonus = False
    if user_id is not None:
        user_data = await api.get_user(user_id)
        if user_data:
            user_has_bonus = user_data.get("bonus_channels_count", 0) >= 1

    await state.clear()

    name = "there"
    if user_id:
        user_data = await api.get_user(user_id)
        if user_data and user_data.get("first_name"):
            name = user_data["first_name"]
    name = html.escape(name)
    channels = await api.get_user_channels_with_meta(user_id) if user_id else []
    mailing_any_on = any(c.get("mailing_enabled") for c in (channels or []))
    await message_manager.send_system(
        chat_id,
        texts.get("welcome_back", name=name),
        reply_markup=get_feed_keyboard(lang, has_bonus_channel=user_has_bonus, mailing_any_on=mailing_any_on),
        tag="menu",
    )
    logger.info("finish_training_flow completed for chat_id=%s", chat_id)


async def send_initial_best_post(
    chat_id: int,
    user_id: int,
    message_manager: MessageManager,
    exclude_post_ids: Optional[List[int]] = None,
    *,
    ml_already_trained: bool = False,
) -> None:
    """Send one best post from M−N (posts not shown in training) after training."""
    from bot.utils import get_html_text_length, TELEGRAM_CAPTION_LIMIT

    api = get_core_api()
    user_bot = get_user_bot()

    await api.update_activity(user_id)
    user_data = await api.get_user(user_id)
    if not user_data:
        return

    if user_data.get("status") == "training":
        return

    if not ml_already_trained:
        result = await api.train_model(user_id)
        if not result or not result.get("success"):
            logger.warning(
                "ML training before best post failed for user %s: %s",
                user_id,
                (result or {}).get("message"),
            )

    all_posts = await api.get_best_posts(user_id, limit=1, exclude_post_ids=exclude_post_ids or [])
    if not all_posts:
        return

    initial_best_post = all_posts[0]
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    question_text = texts.get("feed_post_question", "👆 Как вам данный пост?")

    channel_title = html.escape(initial_best_post.get("channel_title", "Unknown"))
    channel_username = (initial_best_post.get("channel_username") or "").lstrip("@")
    msg_id = initial_best_post.get("telegram_message_id")

    full_text_raw = initial_best_post.get("text") or ""
    if not full_text_raw and channel_username and msg_id:
        full_text_raw = await user_bot.get_post_text(channel_username, msg_id) or ""
    text = full_text_raw

    if channel_username and msg_id:
        header = f'📰 <a href="https://t.me/{channel_username}/{msg_id}">{channel_title}</a>\n\n'
    else:
        header = f"📰 <b>{channel_title}</b>\n\n"
    body = text if text else "<i>[Media content]</i>"
    post_text = header + body

    caption_fits = get_html_text_length(post_text) <= TELEGRAM_CAPTION_LIMIT
    sent_with_caption = False

    if initial_best_post.get("media_type") == "photo":
        media_ids_str = initial_best_post.get("media_file_id") or ""
        media_ids: List[int] = []
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
                tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                media_items: List[InputMediaPhoto] = []
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
                    await message_manager.bot.send_message(
                        chat_id=chat_id,
                        text=post_text,
                        parse_mode="HTML",
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
                    if initial_best_post.get("id"):
                        await message_manager.send_temporary(
                            chat_id,
                            question_text,
                            reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                            tag="feed_post_buttons",
                        )
                    sent_with_caption = True
            else:
                mid = media_ids[0]
                try:
                    photo_bytes = await user_bot.get_photo(channel_username, mid)
                except Exception:
                    photo_bytes = None
                if photo_bytes:
                    if caption_fits:
                        await message_manager.send_regular(
                            chat_id,
                            post_text,
                            tag="feed_post",
                            photo_bytes=photo_bytes,
                            photo_filename=f"{mid}.jpg",
                        )
                        if initial_best_post.get("id"):
                            await message_manager.send_temporary(
                                chat_id,
                                question_text,
                                reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                                tag="feed_post_buttons",
                            )
                        sent_with_caption = True
                    else:
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        await message_manager.bot.send_photo(
                            chat_id=chat_id,
                            photo=input_file,
                        )

    if initial_best_post.get("media_type") == "video" and not sent_with_caption:
        post_id = initial_best_post.get("id")
        photo_bytes = None
        cached_file_id = None
        if post_id:
            cache = get_post_cache()
            content = await cache.get_post_content(post_id)
            if content:
                cached_file_id = content.get("telegram_file_id")
        if cached_file_id:
            if caption_fits:
                await message_manager.send_regular(
                    chat_id,
                    post_text,
                    tag="feed_post",
                    photo=cached_file_id,
                )
            else:
                await message_manager.bot.send_photo(chat_id=chat_id, photo=cached_file_id)
            sent_with_caption = True
            if initial_best_post.get("id"):
                await message_manager.send_temporary(
                    chat_id,
                    question_text,
                    reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                    tag="feed_post_buttons",
                )
        elif channel_username and msg_id:
            try:
                photo_bytes = await user_bot.get_video(channel_username, msg_id)
            except Exception:
                photo_bytes = None
            if photo_bytes:
                if caption_fits:
                    await message_manager.send_regular(
                        chat_id,
                        post_text,
                        tag="feed_post",
                        photo_bytes=photo_bytes,
                        photo_filename=f"{msg_id}.jpg",
                    )
                else:
                    input_file = BufferedInputFile(photo_bytes, filename=f"{msg_id}.jpg")
                    await message_manager.bot.send_photo(chat_id=chat_id, photo=input_file)
                if initial_best_post.get("id"):
                    await message_manager.send_temporary(
                        chat_id,
                        question_text,
                        reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                        tag="feed_post_buttons",
                    )
                sent_with_caption = True

    if not sent_with_caption:
        await message_manager.bot.send_message(
            chat_id=chat_id,
            text=post_text,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        if initial_best_post.get("id"):
            await message_manager.send_temporary(
                chat_id,
                question_text,
                reply_markup=get_feed_post_keyboard(initial_best_post.get("id")),
                tag="feed_post_buttons",
            )
