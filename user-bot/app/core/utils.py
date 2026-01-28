"""
Utility functions for message formatting.
"""
import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telethon.tl.types import Message


def _utf16_offset_to_python(text: str, utf16_offset: int) -> int:
    """Convert UTF-16 offset to Python string index.
    
    Telegram uses UTF-16 code units for entity offsets.
    Python strings use Unicode code points.
    Characters outside BMP (like emoji) use 2 UTF-16 code units (surrogate pairs).
    """
    utf16_pos = 0
    for i, char in enumerate(text):
        if utf16_pos >= utf16_offset:
            return i
        # Characters outside BMP (code point > 0xFFFF) use 2 UTF-16 code units
        if ord(char) > 0xFFFF:
            utf16_pos += 2
        else:
            utf16_pos += 1
    return len(text)


def _apply_nested_formatting(content: str, nested_entities: list, text: str, base_offset: int) -> str:
    """Apply formatting to nested entities within a parent entity.
    
    Args:
        content: The text content to format
        nested_entities: List of entities that are nested within the parent
        text: Full original text (for offset calculations)
        base_offset: UTF-16 offset of the parent entity start
        
    Returns:
        Formatted content with nested formatting applied
    """
    if not nested_entities:
        return html.escape(content)
    
    result = []
    last_end = 0
    
    for entity in nested_entities:
        entity_type = type(entity).__name__
        # Calculate relative position within the content
        rel_start = _utf16_offset_to_python(text, entity.offset) - _utf16_offset_to_python(text, base_offset)
        rel_end = _utf16_offset_to_python(text, entity.offset + entity.length) - _utf16_offset_to_python(text, base_offset)
        
        # Clamp to content bounds
        rel_start = max(0, min(rel_start, len(content)))
        rel_end = max(0, min(rel_end, len(content)))
        
        if rel_start < last_end or rel_start >= rel_end:
            continue
            
        # Add text before this entity
        if rel_start > last_end:
            result.append(html.escape(content[last_end:rel_start]))
        
        nested_content = content[rel_start:rel_end]
        escaped = html.escape(nested_content)
        
        # Apply formatting
        if entity_type == "MessageEntityBold":
            result.append(f"<b>{escaped}</b>")
        elif entity_type == "MessageEntityItalic":
            result.append(f"<i>{escaped}</i>")
        elif entity_type == "MessageEntityUnderline":
            result.append(f"<u>{escaped}</u>")
        elif entity_type == "MessageEntityStrike":
            result.append(f"<s>{escaped}</s>")
        elif entity_type == "MessageEntityTextUrl":
            url = html.escape(entity.url)
            result.append(f'<a href="{url}">{escaped}</a>')
        else:
            result.append(escaped)
        
        last_end = rel_end
    
    # Add remaining content
    if last_end < len(content):
        result.append(html.escape(content[last_end:]))
    
    return ''.join(result)


def get_message_html(message: "Message") -> str:
    """Get message text with HTML formatting.
    
    Converts Telegram entities to HTML format with proper UTF-16 offset handling.
    Supports nested entities (e.g., italic text inside a hyperlink).
    Handles premium/custom emoji by including the text representation.
    
    Args:
        message: Telethon Message object
        
    Returns:
        Formatted text in HTML format
    """
    text = message.raw_text or message.message or ""
    entities = message.entities
    
    if not entities or not text:
        return html.escape(text)
    
    # Sort entities by offset, then by length (longer first for nesting)
    sorted_entities = sorted(entities, key=lambda e: (e.offset, -e.length))
    
    # Separate "container" entities (can have nested content) from "leaf" entities
    container_types = {
        "MessageEntityTextUrl", "MessageEntityBlockquote", "MessageEntitySpoiler"
    }
    formatting_types = {
        "MessageEntityBold", "MessageEntityItalic", "MessageEntityUnderline",
        "MessageEntityStrike", "MessageEntityCode", "MessageEntityPre"
    }
    
    # Build result piece by piece using UTF-16 aware indexing
    result = []
    last_end_utf16 = 0
    processed_ranges = []  # Track which ranges we've already processed
    
    for entity in sorted_entities:
        start_utf16 = entity.offset
        end_utf16 = entity.offset + entity.length
        entity_type = type(entity).__name__
        
        # Convert UTF-16 offsets to Python string indices
        start = _utf16_offset_to_python(text, start_utf16)
        end = _utf16_offset_to_python(text, end_utf16)
        last_end = _utf16_offset_to_python(text, last_end_utf16)
        
        # Skip if this range is already processed (nested entity)
        is_nested = False
        for (ps, pe) in processed_ranges:
            if start >= ps and end <= pe and not (start == ps and end == pe):
                is_nested = True
                break
        if is_nested:
            continue
        
        # Handle overlapping entities - skip but don't lose text
        if start < last_end:
            continue
        
        # Add escaped text before this entity (gap between entities)
        if start > last_end:
            result.append(html.escape(text[last_end:start]))
        
        # Get entity content
        content = text[start:end]
        
        # Find nested entities within this one
        nested = []
        for other in sorted_entities:
            if other is entity:
                continue
            other_start = other.offset
            other_end = other.offset + other.length
            # Check if other is fully contained within this entity
            if other_start >= start_utf16 and other_end <= end_utf16:
                nested.append(other)
        
        # Apply formatting based on entity type
        if entity_type == "MessageEntityBold":
            inner = _apply_nested_formatting(content, nested, text, start_utf16) if nested else html.escape(content)
            result.append(f"<b>{inner}</b>")
        elif entity_type == "MessageEntityItalic":
            inner = _apply_nested_formatting(content, nested, text, start_utf16) if nested else html.escape(content)
            result.append(f"<i>{inner}</i>")
        elif entity_type == "MessageEntityCode":
            result.append(f"<code>{html.escape(content)}</code>")
        elif entity_type == "MessageEntityPre":
            lang = getattr(entity, 'language', '') or ''
            if lang:
                result.append(f"<pre><code class=\"language-{html.escape(lang)}\">{html.escape(content)}</code></pre>")
            else:
                result.append(f"<pre>{html.escape(content)}</pre>")
        elif entity_type == "MessageEntityStrike":
            inner = _apply_nested_formatting(content, nested, text, start_utf16) if nested else html.escape(content)
            result.append(f"<s>{inner}</s>")
        elif entity_type == "MessageEntityUnderline":
            inner = _apply_nested_formatting(content, nested, text, start_utf16) if nested else html.escape(content)
            result.append(f"<u>{inner}</u>")
        elif entity_type == "MessageEntityTextUrl":
            url = html.escape(entity.url)
            inner = _apply_nested_formatting(content, nested, text, start_utf16) if nested else html.escape(content)
            result.append(f'<a href="{url}">{inner}</a>')
        elif entity_type == "MessageEntityUrl":
            result.append(f'<a href="{html.escape(content)}">{html.escape(content)}</a>')
        elif entity_type == "MessageEntityMention":
            result.append(f'<a href="https://t.me/{content[1:]}">{html.escape(content)}</a>')
        elif entity_type == "MessageEntityBlockquote":
            inner = _apply_nested_formatting(content, nested, text, start_utf16) if nested else html.escape(content)
            result.append(f"<blockquote>{inner}</blockquote>")
        elif entity_type == "MessageEntitySpoiler":
            inner = _apply_nested_formatting(content, nested, text, start_utf16) if nested else html.escape(content)
            result.append(f"<tg-spoiler>{inner}</tg-spoiler>")
        elif entity_type == "MessageEntityCustomEmoji":
            # Custom/premium emoji - Bot API doesn't support them in HTML
            # Just include the text representation (the emoji character)
            result.append(html.escape(content))
        else:
            # Unknown entity - just add escaped content
            result.append(html.escape(content))
        
        processed_ranges.append((start, end))
        last_end_utf16 = end_utf16
    
    # Add remaining text after last entity
    last_end = _utf16_offset_to_python(text, last_end_utf16)
    if last_end < len(text):
        result.append(html.escape(text[last_end:]))
    
    return ''.join(result)


def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for MarkdownV2.
    
    Args:
        text: Text to escape
        
    Returns:
        Escaped text safe for MarkdownV2
    """
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def get_message_markdown(message: "Message") -> str:
    """
    Get message text with MarkdownV2 formatting.
    
    Converts Telegram entities to MarkdownV2 format with proper escaping.
    
    Args:
        message: Telethon Message object
        
    Returns:
        Formatted text in MarkdownV2 format
    """
    text = message.raw_text or message.message or ""
    entities = message.entities
    
    if not entities or not text:
        return escape_markdown_v2(text)
    
    # Sort entities by offset
    sorted_entities = sorted(entities, key=lambda e: e.offset)
    
    # Build result piece by piece
    result = []
    last_end = 0
    
    for entity in sorted_entities:
        start = entity.offset
        end = entity.offset + entity.length
        entity_type = type(entity).__name__
        
        # Add escaped text before this entity
        if start > last_end:
            result.append(escape_markdown_v2(text[last_end:start]))
        
        # Get entity content (escaped)
        content = text[start:end]
        escaped_content = escape_markdown_v2(content)
        
        # Apply formatting based on entity type
        if entity_type == "MessageEntityBold":
            result.append(f"*{escaped_content}*")
        elif entity_type == "MessageEntityItalic":
            result.append(f"_{escaped_content}_")
        elif entity_type == "MessageEntityCode":
            # Code doesn't need escaping inside
            result.append(f"`{content}`")
        elif entity_type == "MessageEntityPre":
            result.append(f"```\n{content}\n```")
        elif entity_type == "MessageEntityStrike":
            result.append(f"~{escaped_content}~")
        elif entity_type == "MessageEntityUnderline":
            result.append(f"__{escaped_content}__")
        elif entity_type == "MessageEntityTextUrl":
            # URL needs escaping for special chars
            escaped_url = entity.url.replace(')', '\\)').replace('(', '\\(')
            result.append(f"[{escaped_content}]({escaped_url})")
        elif entity_type == "MessageEntityBlockquote":
            # Blockquote: escape content and add > to each line
            lines = escaped_content.split('\n')
            quoted = '\n'.join(f">{line}" for line in lines)
            result.append(quoted)
        elif entity_type == "MessageEntitySpoiler":
            result.append(f"||{escaped_content}||")
        else:
            # Unknown entity - just add escaped content
            result.append(escaped_content)
        
        last_end = end
    
    # Add remaining text after last entity
    if last_end < len(text):
        result.append(escape_markdown_v2(text[last_end:]))
    
    return ''.join(result)

