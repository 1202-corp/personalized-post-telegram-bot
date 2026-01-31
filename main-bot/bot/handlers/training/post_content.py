"""Post content prefetch, cache, and display for training."""

import asyncio
import base64
import logging
from typing import Optional, Any

from aiogram.types import InputMediaPhoto, BufferedInputFile, InlineKeyboardMarkup

from bot.core import MessageManager
from bot.core.message_registry import ManagedMessage, MessageType
from bot.services import get_user_bot, get_post_cache
from bot.services.media_service import MediaService
from bot.utils import TELEGRAM_CAPTION_LIMIT, get_html_text_length

logger = logging.getLogger(__name__)

_media_service: Optional[MediaService] = None


def get_media_service() -> MediaService:
    """Get or create media service instance."""
    global _media_service
    if _media_service is None:
        _media_service = MediaService(get_user_bot())
    return _media_service


async def prefetch_post_content(post_id: int, channel_username: str, message_id: int) -> None:
    """
    Prefetch post content (text and media) and cache it in Redis.
    """
    try:
        post_cache = get_post_cache()
        cached = await post_cache.get_post_content(post_id)
        if cached:
            return
        user_bot = get_user_bot()
        full_content = await user_bot.get_post_full_content(channel_username, message_id)
        if full_content:
            await post_cache.set_post_content(
                post_id=post_id,
                text=full_content.get("text"),
                media_type=full_content.get("media_type"),
                media_data=full_content.get("media_data"),
            )
            logger.debug("Prefetched and cached post content (post_id=%s)", post_id)
    except Exception as e:
        logger.error("Error prefetching post content (post_id=%s): %s", post_id, e)


async def ensure_first_posts_cached(posts: list, post_cache=None) -> None:
    """Prefetch first two posts in background if not cached."""
    if not posts:
        return
    if post_cache is None:
        post_cache = get_post_cache()
    for i in [0, 1]:
        if i >= len(posts):
            break
        post = posts[i]
        post_id = post.get("id")
        channel_username = (post.get("channel_username") or "").lstrip("@")
        msg_id = post.get("telegram_message_id")
        if post_id and channel_username and msg_id:
            cached = await post_cache.get_post_content(post_id)
            if not cached:
                asyncio.create_task(prefetch_post_content(post_id, channel_username, msg_id))


async def get_post_content_for_display(
    post_id: Optional[int],
    post: dict,
    post_cache: Any,
    user_bot: Any,
) -> dict:
    """
    Get post text and media for display: from cache or fetch from user-bot and cache.
    Returns dict with keys: text, media_type, media_data, telegram_file_id.
    """
    post_text = post.get("text") or ""
    cached_media_type = None
    cached_media_data = None
    cached_telegram_file_id = None
    channel_username = (post.get("channel_username") or "").lstrip("@")
    msg_id = post.get("telegram_message_id")

    if post_id:
        cached_content = await post_cache.get_post_content(post_id)
        if cached_content:
            post_text = cached_content.get("text") or ""
            cached_media_type = cached_content.get("media_type")
            cached_media_data = cached_content.get("media_data")
            cached_telegram_file_id = cached_content.get("telegram_file_id")

    # Fallback: no content in Redis — fetch from user-bot and cache (text + media; telegram_file_id saved after first send)
    message_gone = False
    if not post_text and not cached_media_data and channel_username and msg_id:
        full_content = await user_bot.get_post_full_content(channel_username, msg_id)
        if full_content:
            post_text = full_content.get("text") or ""
            cached_media_type = full_content.get("media_type")
            cached_media_data = full_content.get("media_data")
            if post_id:
                await post_cache.set_post_content(
                    post_id=post_id,
                    text=post_text,
                    media_type=cached_media_type,
                    media_data=cached_media_data,
                )
        else:
            # Message no longer exists in Telegram (deleted) — caller should invalidate post and take another
            message_gone = True

    result = {
        "text": post_text,
        "media_type": cached_media_type,
        "media_data": cached_media_data,
        "telegram_file_id": cached_telegram_file_id,
    }
    if message_gone:
        result["_message_gone"] = True
    return result


async def send_training_post_content(
    chat_id: int,
    post: dict,
    text: str,
    cached_media_type: Optional[str],
    cached_media_data: Optional[str],
    cached_telegram_file_id: Optional[str],
    message_manager: MessageManager,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    lang: str = "en_US",
) -> Optional[int]:
    """
    Send one training post as REGULAR message (text/media + optional 'Open in channel' + Main menu on last).
    Returns the message_id of the sent post (for reaction), or None.
    """
    post_id = post.get("id", 0)
    channel_username = (post.get("channel_username") or "").lstrip("@")
    msg_id = post.get("telegram_message_id")
    caption_fits = get_html_text_length(text) <= TELEGRAM_CAPTION_LIMIT
    post_message_id = None
    media_type_to_use = cached_media_type or post.get("media_type")
    user_bot = get_user_bot()
    media_service = get_media_service()
    post_cache = get_post_cache()

    if media_type_to_use == "photo":
        photo_bytes_from_cache = None
        if cached_media_data:
            try:
                photo_bytes_from_cache = base64.b64decode(cached_media_data.encode("utf-8"))
            except Exception as e:
                logger.warning("Failed to decode cached media_data for post %s: %s", post_id, e)

        media_ids_str = post.get("media_file_id") or ""
        media_ids: list = []
        if media_ids_str:
            for part in media_ids_str.split(","):
                part = part.strip()
                if part.isdigit():
                    media_ids.append(int(part))
        else:
            if isinstance(msg_id, int):
                media_ids.append(msg_id)

        if channel_username and (media_ids or photo_bytes_from_cache):
            cached_photo = await media_service.get_cached_photo(chat_id, post.get("id", 0))
            cached_photos = await media_service.get_cached_photos(chat_id, post.get("id", 0))
            cached = {"photo": cached_photo, "photos": cached_photos} if cached_photo or cached_photos else None
            if photo_bytes_from_cache:
                cached = {"photo": photo_bytes_from_cache}

            if len(media_ids) > 1:
                if cached and cached.get("photos"):
                    photos_data = cached["photos"]
                else:
                    tasks = [user_bot.get_photo(channel_username, mid) for mid in media_ids]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    photos_data = [r for r in results if r and not isinstance(r, Exception)]
                media_items = []
                for i, photo_bytes in enumerate(photos_data):
                    input_file = BufferedInputFile(
                        photo_bytes,
                        filename=f"{media_ids[i] if i < len(media_ids) else i}.jpg",
                    )
                    media_items.append(InputMediaPhoto(media=input_file))
                if media_items:
                    msgs = await message_manager.bot.send_media_group(chat_id=chat_id, media=media_items)
                    for msg in msgs:
                        managed = ManagedMessage(
                            message_id=msg.message_id,
                            chat_id=chat_id,
                            message_type=MessageType.REGULAR,
                            tag="training_post_content",
                        )
                        await message_manager.registry.register(managed)
                    post_message_id = msgs[0].message_id if msgs else None
                    post_msg = await message_manager.send_regular(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup,
                        tag="training_post_content",
                        add_main_menu=False,  # no main menu on posts during training
                        lang=lang,
                    )
                    if post_msg:
                        post_message_id = post_msg.message_id
                else:
                    post_msg = await message_manager.send_regular(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup,
                        tag="training_post_content",
                        add_main_menu=False,  # no main menu on posts during training
                        lang=lang,
                    )
                    if post_msg:
                        post_message_id = post_msg.message_id
            else:
                mid = media_ids[0]
                photo_bytes = None
                if cached_telegram_file_id:
                    post_msg = await message_manager.send_regular(
                        chat_id=chat_id,
                        text=text,
                        photo=cached_telegram_file_id,
                        reply_markup=reply_markup,
                        tag="training_post_content",
                        add_main_menu=False,  # no main menu on posts during training
                        lang=lang,
                    )
                    if post_msg:
                        post_message_id = post_msg.message_id
                else:
                    if cached and cached.get("photo"):
                        photo_bytes = cached["photo"]
                    else:
                        try:
                            photo_bytes = await user_bot.get_photo(channel_username, mid)
                        except Exception:
                            photo_bytes = None
                    if photo_bytes:
                        if caption_fits:
                            post_msg = await message_manager.send_regular(
                                chat_id=chat_id,
                                text=text,
                                photo_bytes=photo_bytes,
                                photo_filename=f"{mid}.jpg",
                                reply_markup=reply_markup,
                                tag="training_post_content",
                                add_main_menu=False,  # no main menu on posts during training
                                lang=lang,
                            )
                            if post_msg:
                                post_message_id = post_msg.message_id
                                # Save telegram file_id so other users can send by file_id (no re-download)
                                if post_id and post_msg.photo:
                                    await post_cache.set_post_content(
                                        post_id, telegram_file_id=post_msg.photo[-1].file_id
                                    )
                        else:
                            input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                            msg = await message_manager.bot.send_photo(chat_id=chat_id, photo=input_file)
                            if post_id and msg.photo:
                                await post_cache.set_post_content(
                                    post_id, telegram_file_id=msg.photo[-1].file_id
                                )
                            managed = ManagedMessage(
                                message_id=msg.message_id,
                                chat_id=chat_id,
                                message_type=MessageType.REGULAR,
                                tag="training_post_content",
                            )
                            await message_manager.registry.register(managed)
                            post_msg = await message_manager.send_regular(
                                chat_id=chat_id,
                                text=text,
                                reply_markup=reply_markup,
                                tag="training_post_content",
                                add_main_menu=False,  # no main menu on posts during training
                                lang=lang,
                            )
                            if post_msg:
                                post_message_id = post_msg.message_id
                    else:
                        post_msg = await message_manager.send_regular(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=reply_markup,
                            tag="training_post_content",
                            add_main_menu=False,  # no main menu on posts during training
                            lang=lang,
                        )
                        if post_msg:
                            post_message_id = post_msg.message_id
        else:
            post_msg = await message_manager.send_regular(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                tag="training_post_content",
                add_main_menu=False,  # no main menu on posts during training
                lang=lang,
            )
            if post_msg:
                post_message_id = post_msg.message_id

    elif media_type_to_use == "video" and channel_username and msg_id:
        photo_bytes = None
        if cached_media_data:
            try:
                photo_bytes = base64.b64decode(cached_media_data.encode("utf-8"))
            except Exception as e:
                logger.warning("Failed to decode cached media_data for video post %s: %s", post_id, e)
        if not photo_bytes:
            cached_video = await media_service.get_cached_video(chat_id, post.get("id", 0))
            if cached_video:
                photo_bytes = cached_video
            else:
                try:
                    photo_bytes = await user_bot.get_video(channel_username, msg_id)
                except Exception:
                    photo_bytes = None
        if cached_telegram_file_id:
            post_msg = await message_manager.send_regular(
                chat_id=chat_id,
                text=text,
                photo=cached_telegram_file_id,
                reply_markup=reply_markup,
                tag="training_post_content",
                add_main_menu=False,  # no main menu on posts during training
                lang=lang,
            )
            if post_msg:
                post_message_id = post_msg.message_id
        elif photo_bytes:
            post_msg = await message_manager.send_regular(
                chat_id=chat_id,
                text=text,
                photo_bytes=photo_bytes,
                photo_filename=f"{msg_id}.jpg",
                reply_markup=reply_markup,
                tag="training_post_content",
                add_main_menu=False,  # no main menu on posts during training
                lang=lang,
            )
            if post_msg:
                post_message_id = post_msg.message_id
                if post_id and post_msg.photo:
                    await post_cache.set_post_content(
                        post_id, telegram_file_id=post_msg.photo[-1].file_id
                    )
        else:
            post_msg = await message_manager.send_regular(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                tag="training_post_content",
                add_main_menu=False,  # no main menu on posts during training
                lang=lang,
            )
            if post_msg:
                post_message_id = post_msg.message_id

    if post_message_id is None:
        post_msg = await message_manager.send_regular(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            tag="training_post_content",
            add_main_menu=False,  # no main menu on posts during training
            lang=lang,
        )
        if post_msg:
            post_message_id = post_msg.message_id

    return post_message_id
