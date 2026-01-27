"""
Utility functions for message formatting.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telethon.tl.types import Message


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

