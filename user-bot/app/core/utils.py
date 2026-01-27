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
    """
    encoded = text.encode('utf-16-le')
    # Each UTF-16 code unit is 2 bytes
    byte_offset = utf16_offset * 2
    if byte_offset > len(encoded):
        byte_offset = len(encoded)
    return len(encoded[:byte_offset].decode('utf-16-le'))


def get_message_html(message: "Message") -> str:
    """Get message text with HTML formatting.
    
    Converts Telegram entities to HTML format with proper UTF-16 offset handling.
    
    Args:
        message: Telethon Message object
        
    Returns:
        Formatted text in HTML format
    """
    text = message.raw_text or message.message or ""
    entities = message.entities
    
    if not entities or not text:
        return html.escape(text)
    
    # Sort entities by offset (handle nested/overlapping later)
    sorted_entities = sorted(entities, key=lambda e: (e.offset, -e.length))
    
    # Build result piece by piece using UTF-16 aware indexing
    result = []
    last_end_utf16 = 0
    
    for entity in sorted_entities:
        start_utf16 = entity.offset
        end_utf16 = entity.offset + entity.length
        entity_type = type(entity).__name__
        
        # Convert UTF-16 offsets to Python string indices
        start = _utf16_offset_to_python(text, start_utf16)
        end = _utf16_offset_to_python(text, end_utf16)
        last_end = _utf16_offset_to_python(text, last_end_utf16)
        
        # Skip if this entity starts before our last position (overlapping)
        if start < last_end:
            continue
        
        # Add escaped text before this entity
        if start > last_end:
            result.append(html.escape(text[last_end:start]))
        
        # Get entity content
        content = text[start:end]
        escaped_content = html.escape(content)
        
        # Apply formatting based on entity type
        if entity_type == "MessageEntityBold":
            result.append(f"<b>{escaped_content}</b>")
        elif entity_type == "MessageEntityItalic":
            result.append(f"<i>{escaped_content}</i>")
        elif entity_type == "MessageEntityCode":
            result.append(f"<code>{escaped_content}</code>")
        elif entity_type == "MessageEntityPre":
            lang = getattr(entity, 'language', '') or ''
            if lang:
                result.append(f"<pre><code class=\"language-{html.escape(lang)}\">{escaped_content}</code></pre>")
            else:
                result.append(f"<pre>{escaped_content}</pre>")
        elif entity_type == "MessageEntityStrike":
            result.append(f"<s>{escaped_content}</s>")
        elif entity_type == "MessageEntityUnderline":
            result.append(f"<u>{escaped_content}</u>")
        elif entity_type == "MessageEntityTextUrl":
            url = html.escape(entity.url)
            result.append(f'<a href="{url}">{escaped_content}</a>')
        elif entity_type == "MessageEntityUrl":
            result.append(f'<a href="{escaped_content}">{escaped_content}</a>')
        elif entity_type == "MessageEntityMention":
            result.append(f'<a href="https://t.me/{content[1:]}">{escaped_content}</a>')
        elif entity_type == "MessageEntityBlockquote":
            result.append(f"<blockquote>{escaped_content}</blockquote>")
        elif entity_type == "MessageEntitySpoiler":
            result.append(f"<tg-spoiler>{escaped_content}</tg-spoiler>")
        else:
            # Unknown entity - just add escaped content
            result.append(escaped_content)
        
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

