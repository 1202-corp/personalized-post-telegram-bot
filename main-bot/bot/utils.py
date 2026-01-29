from typing import Any, Dict, List, Optional, Tuple
from aiogram.types import BufferedInputFile, InputMediaPhoto, InlineKeyboardMarkup

# Telegram caption limit
TELEGRAM_CAPTION_LIMIT = 1024

import html as html_module


async def get_user_lang(user_id: int) -> str:
    """Get user's language preference."""
    from bot.services import get_core_api
    api = get_core_api()
    return await api.get_user_language(user_id)


def escape_md(text: str | None) -> str:
    """Escape user-provided text for HTML parse mode.

    Only escapes <, >, & for HTML. Does NOT escape post text
    which already contains HTML formatting from Telegram.
    """
    if not text:
        return ""
    return html_module.escape(str(text))


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


def markdown_v2_to_html(text: str) -> str:
    """Convert MarkdownV2 formatted text to HTML.
    
    Handles:
    - *bold* -> <b>bold</b>
    - _italic_ -> <i>italic</i>
    - ~strikethrough~ -> <s>strikethrough</s>
    - __underline__ -> <u>underline</u>
    - `code` -> <code>code</code>
    - [text](url) -> <a href="url">text</a>
    - >blockquote -> <blockquote>blockquote</blockquote>
    - ||spoiler|| -> <spoiler>spoiler</spoiler>
    - Removes MarkdownV2 escaping (\, -, ., etc.)
    
    Args:
        text: MarkdownV2 formatted text (may contain escaped characters)
    
    Returns:
        HTML formatted text
    """
    import html
    import re
    
    if not text:
        return ""
    
    # First, unescape MarkdownV2 escaped characters
    # Replace \ followed by special char with just the char
    text = re.sub(r'\\([\\_*\[\]()~`>#+\-=|{}.!])', r'\1', text)
    
    # Convert blockquotes (lines starting with >)
    lines = text.split('\n')
    result_lines = []
    in_blockquote = False
    
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith('>'):
            # Remove > and any leading space after it
            quote_text = stripped[1:].lstrip()
            if not in_blockquote:
                result_lines.append('<blockquote>')
                in_blockquote = True
            result_lines.append(quote_text)
        else:
            if in_blockquote:
                result_lines.append('</blockquote>')
                in_blockquote = False
            result_lines.append(line)
    
    if in_blockquote:
        result_lines.append('</blockquote>')
    
    text = '\n'.join(result_lines)
    
    # Process formatting in order: code blocks, inline code, links, then text formatting
    # This avoids conflicts (e.g., formatting inside code blocks)
    
    # Convert code blocks ```code``` first (highest priority)
    def replace_code_block(match):
        content = match.group(1)
        content_escaped = html.escape(content)
        return f'<pre>{content_escaped}</pre>'
    
    text = re.sub(r'```([^`]+)```', replace_code_block, text)
    
    # Convert inline code `code` (but not inside code blocks)
    def replace_inline_code(match):
        content = match.group(1)
        content_escaped = html.escape(content)
        return f'<code>{content_escaped}</code>'
    
    text = re.sub(r'`([^`]+)`', replace_inline_code, text)
    
    # Convert links [text](url) - handle escaped parentheses in URL
    def replace_link(match):
        link_text = match.group(1)
        url = match.group(2)
        # Unescape URL
        url = url.replace('\\(', '(').replace('\\)', ')')
        # Escape HTML in link text and URL
        link_text_escaped = html.escape(link_text)
        url_escaped = html.escape(url)
        return f'<a href="{url_escaped}">{link_text_escaped}</a>'
    
    # Match [text](url) - handle escaped parentheses
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, text)
    
    # Convert spoiler ||text||
    text = re.sub(r'\|\|([^|]+)\|\|', lambda m: f'<spoiler>{html.escape(m.group(1))}</spoiler>', text)
    
    # Convert underline __text__ (double underscore) before italic _text_
    def replace_underline(match):
        content = match.group(1)
        content_escaped = html.escape(content)
        return f'<u>{content_escaped}</u>'
    
    text = re.sub(r'__([^_]+)__', replace_underline, text)
    
    # Convert bold *text*
    def replace_bold(match):
        content = match.group(1)
        content_escaped = html.escape(content)
        return f'<b>{content_escaped}</b>'
    
    text = re.sub(r'\*([^*]+)\*', replace_bold, text)
    
    # Convert italic _text_ (single underscore, not double)
    def replace_italic(match):
        content = match.group(1)
        content_escaped = html.escape(content)
        return f'<i>{content_escaped}</i>'
    
    text = re.sub(r'(?<!_)_([^_]+)_(?!_)', replace_italic, text)
    
    # Convert strikethrough ~text~
    def replace_strike(match):
        content = match.group(1)
        content_escaped = html.escape(content)
        return f'<s>{content_escaped}</s>'
    
    text = re.sub(r'~([^~]+)~', replace_strike, text)
    
    # Escape any remaining HTML special characters that weren't part of formatting
    # But preserve our HTML tags
    parts = []
    i = 0
    while i < len(text):
        if text[i] == '<':
            # Find closing >
            j = i + 1
            while j < len(text) and text[j] != '>':
                j += 1
            if j < len(text):
                # Found HTML tag - keep as is
                parts.append(text[i:j+1])
                i = j + 1
            else:
                # Unclosed tag - escape it
                parts.append(html.escape(text[i]))
                i += 1
        else:
            # Regular character - collect until next <
            start = i
            while i < len(text) and text[i] != '<':
                i += 1
            if i > start:
                parts.append(html.escape(text[start:i]))
    
    return ''.join(parts)


def get_html_text_length(html_text: str) -> int:
    """Get the length of HTML text as Telegram counts it (excluding tags).
    
    Telegram counts only the visible text length, not HTML tags.
    
    Args:
        html_text: HTML formatted text
    
    Returns:
        Length of text without HTML tags
    """
    import re
    # Remove HTML tags
    text_without_tags = re.sub(r'<[^>]+>', '', html_text)
    return len(text_without_tags)


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
    text = full_text_raw  # Already HTML formatted from user-bot, don't escape
    
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
