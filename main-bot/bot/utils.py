from typing import Any, Dict, List, Optional, Tuple
from aiogram.types import BufferedInputFile, InputMediaPhoto, InlineKeyboardMarkup

# Telegram caption limit
TELEGRAM_CAPTION_LIMIT = 1024

_MD_V2_SPECIAL_CHARS = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!', '\\']


def escape_md(text: str | None) -> str:
    """Escape user-provided text for MarkdownV2 parse mode.

    We keep our own formatting (headers, bold, etc.) in templates
    and only apply this to dynamic values (user names, channel titles,
    post bodies, usernames) to avoid 'can't parse entities' errors.
    """
    if not text:
        return ""
    result = str(text)
    # Escape backslash first to avoid double-escaping
    result = result.replace('\\', '\\\\')
    for ch in _MD_V2_SPECIAL_CHARS[:-1]:  # Skip backslash, already done
        result = result.replace(ch, f'\\{ch}')
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


# DEPRECATED: send_post_with_media and cleanup_media_messages moved to services/post_service.py
# These functions are kept for backwards compatibility but should not be used in new code.
