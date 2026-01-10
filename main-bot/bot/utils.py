from typing import Any, Dict, List, Optional, Tuple
from aiogram.types import BufferedInputFile, InputMediaPhoto, InlineKeyboardMarkup

# Telegram caption limit
TELEGRAM_CAPTION_LIMIT = 1024

_MD_SPECIAL_CHARS = ("\\", "_", "*", "`", "[")


def escape_md(text: str | None) -> str:
    """Escape user-provided text for Markdown parse mode.

    We keep our own formatting (headers, bold, etc.) in templates
    and only apply this to dynamic values (user names, channel titles,
    post bodies, usernames) to avoid 'can't parse entities' errors.
    """
    if not text:
        return ""
    result = str(text)
    for ch in _MD_SPECIAL_CHARS:
        result = result.replace(ch, f"\\{ch}")
    return result


def format_post_text(
    post: Dict[str, Any],
    include_relevance: bool = False,
) -> str:
    """Format post text with channel header.
    
    Args:
        post: Post data dict with 'channel_title', 'text', 'relevance_score'
        include_relevance: Whether to show relevance score (for feed posts)
    
    Returns:
        Formatted markdown text
    """
    channel_title = escape_md(post.get("channel_title", "Unknown"))
    full_text_raw = post.get("text") or ""
    text = escape_md(full_text_raw)
    
    header = f"📰 *{channel_title}*\n"
    
    if include_relevance:
        score = post.get("relevance_score", 0)
        header += f"_Relevance: {int(score * 100)}%_\n\n"
    else:
        header += "\n"
    
    body = text if text else "_[Media content]_"
    return header + body


def parse_media_ids(post: Dict[str, Any]) -> List[int]:
    """Extract media message IDs from post data.
    
    Args:
        post: Post data dict with 'media_file_id' or 'telegram_message_id'
    
    Returns:
        List of telegram message IDs for media
    """
    media_ids_str = post.get("media_file_id") or ""
    media_ids: List[int] = []
    
    if media_ids_str:
        for part in media_ids_str.split(","):
            part = part.strip()
            if part.isdigit():
                media_ids.append(int(part))
    else:
        msg_id = post.get("telegram_message_id")
        if isinstance(msg_id, int):
            media_ids.append(msg_id)
    
    return media_ids


async def send_post_with_media(
    chat_id: int,
    post: Dict[str, Any],
    message_manager: Any,  # MessageManager - avoid circular import
    user_bot: Any,  # UserBotClient - avoid circular import
    keyboard: Optional[InlineKeyboardMarkup] = None,
    tag: str = "post",
    message_type: str = "ephemeral",  # "ephemeral", "onetime", or "system"
    include_relevance: bool = False,
) -> Tuple[bool, List[int]]:
    """Send a post with optional media to chat.
    
    Handles single photos, photo albums, and text-only posts.
    Uses caption when text fits within Telegram limit.
    
    Args:
        chat_id: Telegram chat ID
        post: Post data dict
        message_manager: MessageManager instance
        user_bot: UserBotClient instance for fetching photos
        keyboard: Optional inline keyboard
        tag: Message tag for message_manager
        message_type: Type of message (ephemeral, onetime, system)
        include_relevance: Include relevance score in text
    
    Returns:
        Tuple of (sent_with_caption: bool, media_message_ids: List[int])
    """
    post_text = format_post_text(post, include_relevance=include_relevance)
    caption_fits = len(post_text) <= TELEGRAM_CAPTION_LIMIT
    sent_with_caption = False
    media_message_ids: List[int] = []
    
    # Determine send method based on message_type
    if message_type == "ephemeral":
        send_method = message_manager.send_ephemeral
    elif message_type == "onetime":
        send_method = message_manager.send_onetime
    else:
        send_method = message_manager.send_system
    
    # Handle media posts
    if post.get("media_type") == "photo":
        channel_username = post.get("channel_username")
        media_ids = parse_media_ids(post)
        
        if channel_username and media_ids:
            if len(media_ids) > 1:
                # Send album
                media_items: List[InputMediaPhoto] = []
                for mid in media_ids:
                    try:
                        photo_bytes = await user_bot.get_photo(channel_username, mid)
                    except Exception:
                        photo_bytes = None
                    if not photo_bytes:
                        continue
                    input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                    media_items.append(InputMediaPhoto(media=input_file))
                
                if media_items:
                    msgs = await message_manager.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_items,
                    )
                    media_message_ids.extend(m.message_id for m in msgs)
            else:
                # Single photo
                mid = media_ids[0]
                try:
                    photo_bytes = await user_bot.get_photo(channel_username, mid)
                except Exception:
                    photo_bytes = None
                
                if photo_bytes:
                    if caption_fits:
                        # Delete previous message with same tag
                        if message_type == "ephemeral":
                            await message_manager.delete_ephemeral(chat_id, tag=tag)
                        
                        await send_method(
                            chat_id,
                            post_text,
                            reply_markup=keyboard,
                            tag=tag,
                            photo_bytes=photo_bytes,
                            photo_filename=f"{mid}.jpg",
                        )
                        sent_with_caption = True
                    else:
                        # Send photo separately
                        input_file = BufferedInputFile(photo_bytes, filename=f"{mid}.jpg")
                        msg = await message_manager.bot.send_photo(
                            chat_id=chat_id,
                            photo=input_file,
                        )
                        media_message_ids.append(msg.message_id)
    
    # Send text message if not sent with caption
    if not sent_with_caption:
        if message_type == "ephemeral":
            await message_manager.delete_ephemeral(chat_id, tag=tag)
        
        await send_method(
            chat_id,
            post_text,
            reply_markup=keyboard,
            tag=tag,
        )
    
    return sent_with_caption, media_message_ids


async def cleanup_media_messages(
    chat_id: int,
    message_ids: List[int],
    bot: Any,  # Bot instance
) -> None:
    """Clean up media messages by IDs.
    
    Args:
        chat_id: Telegram chat ID
        message_ids: List of message IDs to delete
        bot: Bot instance
    """
    for mid in message_ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass
