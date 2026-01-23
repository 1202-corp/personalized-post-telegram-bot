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


def escape_md_preserve_formatting(text: str | None) -> str:
    """Escape MarkdownV2 text while preserving formatting.
    
    This function escapes special characters that are NOT part of Markdown formatting.
    It preserves: *bold*, _italic_, `code`, [links](url), etc.
    
    Strategy:
    1. Find all formatting markers (*, _, `, [, ], (, ))
    2. Escape special chars outside of formatting
    3. Keep formatting markers intact
    """
    if not text:
        return ""
    
    import re
    
    # Pattern to match MarkdownV2 formatting:
    # - *bold* or _italic_ (but not standalone * or _)
    # - `code`
    # - [link](url)
    # - Already escaped characters (\*)
    
    # First, protect already escaped characters
    protected = []
    parts = []
    i = 0
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text):
            # Already escaped character
            protected.append((i, i + 2))
            parts.append((i, i + 2, text[i:i+2]))
            i += 2
        elif text[i] in ['*', '_', '`']:
            # Potential formatting marker - find matching pair
            marker = text[i]
            # Look for closing marker (simple heuristic)
            j = i + 1
            while j < len(text) and text[j] != marker:
                if text[j] == '\\':
                    j += 2  # Skip escaped char
                else:
                    j += 1
            if j < len(text) and text[j] == marker:
                # Found matching pair - protect this range
                protected.append((i, j + 1))
                parts.append((i, j + 1, text[i:j+1]))
                i = j + 1
            else:
                # No match, treat as regular char
                i += 1
        elif text[i] == '[':
            # Potential link - find [text](url)
            j = i + 1
            while j < len(text) and text[j] != ']':
                if text[j] == '\\':
                    j += 2
                else:
                    j += 1
            if j < len(text) and text[j] == ']':
                # Found ], now look for (url)
                k = j + 1
                while k < len(text) and text[k] != '(':
                    if text[k] == '\\':
                        k += 2
                    else:
                        k += 1
                if k < len(text) and text[k] == '(':
                    # Find closing )
                    l = k + 1
                    while l < len(text) and text[l] != ')':
                        if text[l] == '\\':
                            l += 2
                        else:
                            l += 1
                    if l < len(text) and text[l] == ')':
                        # Found complete link - protect
                        protected.append((i, l + 1))
                        parts.append((i, l + 1, text[i:l+1]))
                        i = l + 1
                    else:
                        i += 1
                else:
                    i += 1
            else:
                i += 1
        else:
            i += 1
    
    # Now escape unprotected parts
    result = []
    last_end = 0
    
    for start, end, content in sorted(parts, key=lambda x: x[0]):
        # Add escaped text before this protected part
        if start > last_end:
            unprotected = text[last_end:start]
            result.append(escape_md(unprotected))
        # Add protected part as-is
        result.append(content)
        last_end = end
    
    # Add remaining text
    if last_end < len(text):
        result.append(escape_md(text[last_end:]))
    
    return ''.join(result) if result else escape_md(text)


def format_post_text(
    post: Dict[str, Any],
    include_relevance: bool = False,
) -> str:
    """Format post text with channel header.
    
    Args:
        post: Post data dict with 'channel_title', 'text', 'relevance_score'
        include_relevance: Whether to show relevance score (for feed posts)
    
    Returns:
        Formatted HTML text
    """
    import html
    channel_title = html.escape(post.get("channel_title", "Unknown"))
    full_text_raw = post.get("text") or ""
    text = html.escape(full_text_raw)
    
    header = f"📰 <b>{channel_title}</b>\n"
    
    if include_relevance:
        score = post.get("relevance_score", 0)
        header += f"<i>Relevance: {int(score * 100)}%</i>\n\n"
    else:
        header += "\n"
    
    body = text if text else "<i>[Media content]</i>"
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
