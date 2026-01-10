"""
MessageManager - Registry pattern implementation for managing message types.

Message Types:
- SYSTEM: Persistent menu messages (edited, not deleted until trigger)
- EPHEMERAL: Temporary messages (deleted after interaction)
- ONETIME: Feed posts (kept in history, never deleted)
"""

import asyncio
import logging
from enum import Enum
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime
from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, BufferedInputFile, LinkPreviewOptions
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Types of messages managed by MessageManager."""
    SYSTEM = "system"      # Persistent menu, edited in place
    EPHEMERAL = "ephemeral"  # Temporary, deleted after interaction
    ONETIME = "onetime"    # Feed posts, kept forever


@dataclass
class ManagedMessage:
    """Represents a message managed by MessageManager."""
    message_id: int
    chat_id: int
    message_type: MessageType
    created_at: datetime = field(default_factory=datetime.utcnow)
    tag: Optional[str] = None  # Optional tag for grouping (e.g., "menu", "training_post")


class MessageRegistry:
    """
    Thread-safe registry for tracking messages per chat.
    Uses a nested dict structure: {chat_id: {message_type: [ManagedMessage, ...]}}
    """
    
    def __init__(self):
        self._registry: Dict[int, Dict[MessageType, List[ManagedMessage]]] = {}
        self._lock = asyncio.Lock()
    
    async def register(self, message: ManagedMessage) -> None:
        """Register a new message."""
        async with self._lock:
            if message.chat_id not in self._registry:
                self._registry[message.chat_id] = {t: [] for t in MessageType}
            self._registry[message.chat_id][message.message_type].append(message)
    
    async def get_messages(
        self,
        chat_id: int,
        message_type: MessageType,
        tag: Optional[str] = None
    ) -> List[ManagedMessage]:
        """Get all messages of a type for a chat."""
        async with self._lock:
            if chat_id not in self._registry:
                return []
            messages = self._registry[chat_id].get(message_type, [])
            if tag:
                messages = [m for m in messages if m.tag == tag]
            return messages.copy()
    
    async def get_latest(
        self,
        chat_id: int,
        message_type: MessageType,
        tag: Optional[str] = None
    ) -> Optional[ManagedMessage]:
        """Get the latest message of a type for a chat."""
        messages = await self.get_messages(chat_id, message_type, tag)
        return messages[-1] if messages else None
    
    async def remove(self, chat_id: int, message_id: int) -> bool:
        """Remove a message from registry."""
        async with self._lock:
            if chat_id not in self._registry:
                return False
            for msg_type in MessageType:
                msgs = self._registry[chat_id].get(msg_type, [])
                for i, msg in enumerate(msgs):
                    if msg.message_id == message_id:
                        msgs.pop(i)
                        return True
            return False
    
    async def clear_type(self, chat_id: int, message_type: MessageType) -> List[int]:
        """Clear all messages of a type for a chat. Returns cleared message IDs."""
        async with self._lock:
            if chat_id not in self._registry:
                return []
            messages = self._registry[chat_id].get(message_type, [])
            message_ids = [m.message_id for m in messages]
            self._registry[chat_id][message_type] = []
            return message_ids
    
    async def clear_chat(self, chat_id: int) -> Dict[MessageType, List[int]]:
        """Clear all tracked messages for a chat. Returns dict of message IDs by type."""
        async with self._lock:
            if chat_id not in self._registry:
                return {}
            result = {}
            for msg_type in MessageType:
                messages = self._registry[chat_id].get(msg_type, [])
                result[msg_type] = [m.message_id for m in messages]
            del self._registry[chat_id]
            return result


class MessageManager:
    """
    Central manager for all bot messages.
    Implements Registry pattern for tracking and managing message lifecycle.
    """
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.registry = MessageRegistry()
    
    # ============== Core Send Methods ==============
    
    async def send_system(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        tag: str = "menu",
        photo: Optional[str] = None,
        replace_existing: bool = True
    ) -> Optional[Message]:
        """
        Send a SYSTEM message (persistent menu).
        If replace_existing=True, edits the existing system message with same tag.
        Otherwise, deletes old and sends new.
        """
        existing = await self.registry.get_latest(chat_id, MessageType.SYSTEM, tag)
        
        if existing and replace_existing:
            # Try to edit existing message
            try:
                if photo:
                    # Can't change photo to text easily, delete and resend
                    await self._delete_message(chat_id, existing.message_id)
                    await self.registry.remove(chat_id, existing.message_id)
                else:
                    await self.bot.edit_message_text(
                        text=text,
                        chat_id=chat_id,
                        message_id=existing.message_id,
                        reply_markup=reply_markup
                    )
                    return None  # Edited in place
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    return None  # Same content, no change needed
                # Message deleted or other error, send new
                await self.registry.remove(chat_id, existing.message_id)
        elif existing:
            # Delete existing before sending new
            await self._delete_message(chat_id, existing.message_id)
            await self.registry.remove(chat_id, existing.message_id)
        
        # Send new message
        try:
            if photo:
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                )
            else:
                message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                )
            
            managed = ManagedMessage(
                message_id=message.message_id,
                chat_id=chat_id,
                message_type=MessageType.SYSTEM,
                tag=tag
            )
            await self.registry.register(managed)
            return message
        except Exception as e:
            logger.error(f"Failed to send system message: {e}")
            return None
    
    async def send_ephemeral(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        tag: Optional[str] = None,
        auto_delete_after: Optional[float] = None,
        photo_bytes: Optional[bytes] = None,
        photo_filename: str = "photo.jpg",
        disable_link_preview: bool = False,
    ) -> Optional[Message]:
        """
        Send an EPHEMERAL message (temporary, deleted after interaction).
        If auto_delete_after is set, message is deleted after that many seconds.
        """
        try:
            if photo_bytes:
                input_file = BufferedInputFile(photo_bytes, filename=photo_filename)
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=input_file,
                    caption=text,
                    reply_markup=reply_markup,
                )
            else:
                message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    link_preview_options=LinkPreviewOptions(is_disabled=True) if disable_link_preview else None,
                )
            
            managed = ManagedMessage(
                message_id=message.message_id,
                chat_id=chat_id,
                message_type=MessageType.EPHEMERAL,
                tag=tag
            )
            await self.registry.register(managed)
            
            if auto_delete_after:
                asyncio.create_task(
                    self._auto_delete(chat_id, message.message_id, auto_delete_after)
                )
            
            return message
        except Exception as e:
            logger.error(f"Failed to send ephemeral message: {e}")
            return None
    
    async def send_onetime(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        photo: Optional[str] = None,
        tag: Optional[str] = None,
        photo_bytes: Optional[bytes] = None,
        photo_filename: str = "photo.jpg",
    ) -> Optional[Message]:
        """
        Send a ONETIME message (feed post, kept in history).
        These messages are tracked but never auto-deleted.
        """
        try:
            if photo_bytes:
                input_file = BufferedInputFile(photo_bytes, filename=photo_filename)
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=input_file,
                    caption=text,
                    reply_markup=reply_markup,
                )
            elif photo:
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                )
            else:
                message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            
            managed = ManagedMessage(
                message_id=message.message_id,
                chat_id=chat_id,
                message_type=MessageType.ONETIME,
                tag=tag
            )
            await self.registry.register(managed)
            return message
        except Exception as e:
            logger.error(f"Failed to send onetime message: {e}")
            return None
    
    # ============== Deletion Methods ==============
    
    async def delete_ephemeral(
        self,
        chat_id: int,
        message_id: Optional[int] = None,
        tag: Optional[str] = None
    ) -> int:
        """
        Delete ephemeral message(s).
        If message_id is provided, delete that specific message.
        If tag is provided, delete all ephemeral messages with that tag.
        Otherwise, delete all ephemeral messages for the chat.
        Returns count of deleted messages.
        """
        deleted_count = 0
        
        if message_id:
            if await self._delete_message(chat_id, message_id):
                await self.registry.remove(chat_id, message_id)
                deleted_count = 1
        else:
            messages = await self.registry.get_messages(chat_id, MessageType.EPHEMERAL, tag)
            for msg in messages:
                if await self._delete_message(chat_id, msg.message_id):
                    await self.registry.remove(chat_id, msg.message_id)
                    deleted_count += 1
        
        return deleted_count
    
    async def delete_system(self, chat_id: int, tag: Optional[str] = None) -> int:
        """Delete system message(s) by tag or all if no tag."""
        deleted_count = 0
        messages = await self.registry.get_messages(chat_id, MessageType.SYSTEM, tag)
        
        for msg in messages:
            if await self._delete_message(chat_id, msg.message_id):
                await self.registry.remove(chat_id, msg.message_id)
                deleted_count += 1
        
        return deleted_count
    
    async def cleanup_chat(
        self,
        chat_id: int,
        include_system: bool = False,
        include_onetime: bool = False
    ) -> Dict[str, int]:
        """
        Clean up messages for a chat.
        By default, only deletes ephemeral messages.
        """
        result = {"ephemeral": 0, "system": 0, "onetime": 0}
        
        # Always clean ephemeral
        result["ephemeral"] = await self.delete_ephemeral(chat_id)
        
        if include_system:
            result["system"] = await self.delete_system(chat_id)
        
        # OneTime messages are NOT deleted by design
        if include_onetime:
            messages = await self.registry.get_messages(chat_id, MessageType.ONETIME)
            for msg in messages:
                if await self._delete_message(chat_id, msg.message_id):
                    await self.registry.remove(chat_id, msg.message_id)
                    result["onetime"] += 1
        
        return result
    
    # ============== Edit Methods ==============
    
    async def edit_system(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        tag: str = "menu"
    ) -> bool:
        """Edit the existing system message with given tag."""
        existing = await self.registry.get_latest(chat_id, MessageType.SYSTEM, tag)
        if not existing:
            return False
        
        try:
            await self.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=existing.message_id,
                reply_markup=reply_markup
            )
            return True
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return True  # Same content, considered success
            logger.error(f"Failed to edit system message: {e}")
            return False
    
    async def edit_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> bool:
        """Edit reply markup of any tracked message."""
        try:
            await self.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup
            )
            return True
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return True
            logger.error(f"Failed to edit reply markup: {e}")
            return False
    
    # ============== Helper Methods ==============
    
    async def _delete_message(self, chat_id: int, message_id: int) -> bool:
        """Safely delete a message, handling errors gracefully."""
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except TelegramBadRequest as e:
            if "message to delete not found" in str(e):
                return True  # Already deleted
            if "message can't be deleted" in str(e):
                logger.warning(f"Cannot delete message {message_id}: {e}")
                return False
            logger.error(f"Error deleting message {message_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting message {message_id}: {e}")
            return False
    
    async def _auto_delete(self, chat_id: int, message_id: int, delay: float) -> None:
        """Auto-delete a message after delay."""
        await asyncio.sleep(delay)
        await self._delete_message(chat_id, message_id)
        await self.registry.remove(chat_id, message_id)
    
    # ============== Utility Methods ==============
    
    async def answer_callback_and_delete(
        self,
        callback_query,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> None:
        """Answer callback query and delete the ephemeral message."""
        try:
            await callback_query.answer(text=text, show_alert=show_alert)
        except Exception as e:
            logger.error(f"Error answering callback: {e}")
        
        # Delete the message that had the callback button
        await self.delete_ephemeral(
            callback_query.message.chat.id,
            callback_query.message.message_id
        )
    
    async def transition_to_system(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        tag: str = "menu",
        cleanup_ephemeral: bool = True
    ) -> Optional[Message]:
        """
        Transition to a system message state.
        Cleans up ephemeral messages and sends/updates system message.
        """
        if cleanup_ephemeral:
            await self.delete_ephemeral(chat_id)
        
        return await self.send_system(chat_id, text, reply_markup, tag)
