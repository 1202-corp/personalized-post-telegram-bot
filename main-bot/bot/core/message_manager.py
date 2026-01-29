"""
MessageManager - Central manager for all bot messages.

Implements Registry pattern for tracking and managing message lifecycle.
"""

import asyncio
import logging
from typing import Optional, Dict, List

from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, BufferedInputFile, LinkPreviewOptions, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from bot.core.message_registry import MessageRegistry, MessageType, ManagedMessage

logger = logging.getLogger(__name__)


class MessageManager:
    """
    Central manager for all bot messages.
    Implements Registry pattern for tracking and managing message lifecycle.
    """
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.registry = MessageRegistry()
        self._is_start_command: Dict[int, bool] = {}  # Track if /start was called
    
    # ============== Core Send Methods ==============
    
    async def send_system(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        tag: str = "menu",
        photo: Optional[str] = None,
        photo_bytes: Optional[bytes] = None,
        photo_filename: str = "photo.jpg",
        is_start: bool = False
    ) -> Optional[Message]:
        """
        Send a SYSTEM message (persistent menu).
        
        Logic:
        - Always deletes ALL temporary messages before sending/editing
        - Checks if should recreate (send new then delete old) or edit existing
        - When recreating: sends NEW first, then deletes OLD
        """
        # Mark if this is a /start command
        if is_start:
            self._is_start_command[chat_id] = True
        
        # Always delete all temporary messages first (including user messages)
        await self._delete_all_temporary(chat_id)
        
        existing = await self.registry.get_latest(chat_id, MessageType.SYSTEM, tag)
        
        # Check if we should recreate instead of edit
        should_recreate = await self._should_recreate_system(
            chat_id, existing, photo, photo_bytes, is_start
        )
        
        if should_recreate:
            # RECREATE: Send new first, then delete old
            new_message = await self._send_new_system(
                chat_id, text, reply_markup, tag, photo, photo_bytes, photo_filename
            )
            
            # Delete old system message if exists
            if existing:
                await self._delete_message(chat_id, existing.message_id)
                await self.registry.remove(chat_id, existing.message_id)
            
            return new_message
        else:
            # EDIT: Try to edit existing
            if existing:
                try:
                    if photo or photo_bytes:
                        # Existing may be photo message — try editing caption to avoid recreating
                        try:
                            await self.bot.edit_message_caption(
                                chat_id=chat_id,
                                message_id=existing.message_id,
                                caption=text,
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.HTML,
                            )
                            return None  # Edited in place, avatar preserved
                        except TelegramBadRequest as cap_e:
                            if "message is not modified" in str(cap_e).lower():
                                return None
                            # Existing is text or caption edit failed, recreate
                            pass
                        new_message = await self._send_new_system(
                            chat_id, text, reply_markup, tag, photo, photo_bytes, photo_filename
                        )
                        await self._delete_message(chat_id, existing.message_id)
                        await self.registry.remove(chat_id, existing.message_id)
                        return new_message
                    else:
                        # Edit text message
                        await self.bot.edit_message_text(
                            text=text,
                            chat_id=chat_id,
                            message_id=existing.message_id,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                        return None  # Edited in place
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e).lower():
                        return None  # Same content, no change needed
                    # Message may be photo — try edit_message_caption before recreating
                    try:
                        await self.bot.edit_message_caption(
                            chat_id=chat_id,
                            message_id=existing.message_id,
                            caption=text,
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML,
                        )
                        return None
                    except TelegramBadRequest:
                        pass
                    except Exception:
                        pass
                    logger.warning(f"Failed to edit system message, recreating: {e}")
                    new_message = await self._send_new_system(
                        chat_id, text, reply_markup, tag, photo, photo_bytes, photo_filename
                    )
                    await self._delete_message(chat_id, existing.message_id)
                    await self.registry.remove(chat_id, existing.message_id)
                    return new_message
            else:
                # No existing, just send new
                return await self._send_new_system(
                    chat_id, text, reply_markup, tag, photo, photo_bytes, photo_filename
                )
    
    async def send_temporary(
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
        Send a TEMPORARY message.
        These messages are deleted when system or regular messages are sent.
        """
        try:
            if photo_bytes:
                input_file = BufferedInputFile(photo_bytes, filename=photo_filename)
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=input_file,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            else:
                message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
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
            logger.error(f"Failed to send temporary message: {e}")
            return None
    
    async def send_regular(
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
        Send a REGULAR message (posts, kept forever).
        These messages are tracked but never auto-deleted.
        Deletes all temporary messages before sending.
        """
        # Delete all temporary messages before sending regular (including user messages)
        await self._delete_all_temporary(chat_id)
        
        try:
            if photo_bytes:
                input_file = BufferedInputFile(photo_bytes, filename=photo_filename)
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=input_file,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            elif photo:
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            else:
                message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            
            managed = ManagedMessage(
                message_id=message.message_id,
                chat_id=chat_id,
                message_type=MessageType.REGULAR,
                tag=tag
            )
            await self.registry.register(managed)
            return message
        except Exception as e:
            logger.error(f"Failed to send regular message: {e}")
            return None
    
    async def send_toast(
        self,
        callback_query: CallbackQuery,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> None:
        """
        Send a toast notification (popup).
        This doesn't create a message in chat, only shows a popup notification.
        """
        try:
            await callback_query.answer(text=text, show_alert=show_alert)
        except Exception as e:
            logger.error(f"Error sending toast: {e}")
    
    # ============== Deletion Methods ==============
    
    async def delete_temporary(
        self,
        chat_id: int,
        message_id: Optional[int] = None,
        tag: Optional[str] = None
    ) -> int:
        """
        Delete temporary message(s).
        If message_id is provided, delete that specific message.
        If tag is provided, delete all temporary messages with that tag.
        Otherwise, delete all temporary messages for the chat.
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
    
    async def delete_user_message(self, message: Message) -> bool:
        """
        Delete a user's message.
        Used to clean up user messages like /start, /help, etc.
        Marks message as deleted to prevent middleware from deleting it again.
        """
        try:
            await self.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
            # Mark as deleted to prevent middleware from deleting it again
            message._deleted = True
            return True
        except TelegramBadRequest as e:
            if "message to delete not found" in str(e).lower():
                # Mark as deleted even if already deleted
                message._deleted = True
                return True  # Already deleted
            logger.warning(f"Cannot delete user message {message.message_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error deleting user message {message.message_id}: {e}")
            return False
    
    async def cleanup_chat(
        self,
        chat_id: int,
        include_system: bool = False,
        include_regular: bool = False
    ) -> Dict[str, int]:
        """
        Clean up messages for a chat.
        By default, only deletes temporary messages.
        """
        result = {"temporary": 0, "system": 0, "regular": 0}
        
        # Always clean temporary
        result["temporary"] = await self.delete_temporary(chat_id)
        
        if include_system:
            result["system"] = await self.delete_system(chat_id)
        
        if include_regular:
            messages = await self.registry.get_messages(chat_id, MessageType.REGULAR)
            for msg in messages:
                if await self._delete_message(chat_id, msg.message_id):
                    await self.registry.remove(chat_id, msg.message_id)
                    result["regular"] += 1
        
        return result
    
    # ============== Edit Methods ==============
    
    async def edit_system(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        tag: str = "menu"
    ) -> bool:
        """
        Edit the existing system message with given tag.
        
        If regular messages exist after the system message, recreates it instead of editing.
        """
        # Delete all temporary messages before editing (same as send_system)
        await self._delete_all_temporary(chat_id)
        
        existing = await self.registry.get_latest(chat_id, MessageType.SYSTEM, tag)
        if not existing:
            return False
        
        # Check if there are regular messages after system message
        # If yes, we need to recreate instead of edit
        regular_messages = await self.registry.get_messages(chat_id, MessageType.REGULAR)
        should_recreate = False
        for reg_msg in regular_messages:
            if reg_msg.message_id > existing.message_id:
                should_recreate = True
                break
        
        if should_recreate:
            # Recreate: send new first, then delete old
            new_message = await self._send_new_system(
                chat_id, text, reply_markup, tag, None, None, "photo.jpg"
            )
            if new_message:
                await self._delete_message(chat_id, existing.message_id)
                await self.registry.remove(chat_id, existing.message_id)
                return True
            return False
        
        # Try to edit existing (text message only). If existing is a photo message,
        # edit_message_text fails — then we must recreate (delete photo msg, send text)
        # so the avatar disappears when going back from channel detail.
        try:
            await self.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=existing.message_id,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            return True
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return True  # Same content, considered success
            # Existing message has media (e.g. photo); we want text-only. Do not
            # edit_message_caption (that would keep the photo). Recreate instead.
            logger.debug(f"System message is not plain text, recreating: {e}")
            new_message = await self._send_new_system(
                chat_id, text, reply_markup, tag, None, None, "photo.jpg"
            )
            if new_message:
                await self._delete_message(chat_id, existing.message_id)
                await self.registry.remove(chat_id, existing.message_id)
                return True
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
            if "message is not modified" in str(e).lower():
                return True
            logger.error(f"Failed to edit reply markup: {e}")
            return False
    
    # ============== Helper Methods ==============
    
    async def _should_recreate_system(
        self,
        chat_id: int,
        existing: Optional[ManagedMessage],
        photo: Optional[str],
        photo_bytes: Optional[bytes],
        is_start: bool
    ) -> bool:
        """
        Check if system message should be recreated instead of edited.
        
        Conditions for recreation (in priority order):
        1. /start command was called (always recreate)
        2. System message not found or deleted
        3. After system message there are regular messages (CRITICAL RULE)
        4. Need to add/remove photo (current state is opposite)
        5. Error occurred when trying to edit
        """
        # Always recreate on /start
        if is_start or self._is_start_command.get(chat_id, False):
            self._is_start_command.pop(chat_id, None)  # Clear flag
            return True
        
        # No existing message, need to create
        if not existing:
            return True
        
        # CRITICAL RULE: Check if there are regular messages after system message
        # If regular messages exist after system, ALWAYS recreate (don't edit)
        # In Telegram, message_id always increases, so we check by message_id
        regular_messages = await self.registry.get_messages(chat_id, MessageType.REGULAR)
        if regular_messages:
            # Check if any regular message has higher message_id than system (sent after)
            for reg_msg in regular_messages:
                if reg_msg.message_id > existing.message_id:
                    logger.debug(
                        f"Recreating system message: regular message {reg_msg.message_id} "
                        f"exists after system message {existing.message_id}"
                    )
                    return True  # Regular message after system, MUST recreate
        
        # Check if message still exists (try to get it)
        try:
            await self.bot.get_chat(chat_id)
        except Exception:
            return True  # Chat not accessible, recreate
        
        # Check if need to change photo state
        has_photo = photo is not None or photo_bytes is not None
        # We can't easily check if existing has photo, so we'll try edit first
        # This will be handled in send_system logic
        
        return False
    
    async def _delete_all_temporary(self, chat_id: int) -> int:
        """Delete all temporary messages for a chat."""
        return await self.delete_temporary(chat_id)
    
    async def _send_new_system(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup],
        tag: str,
        photo: Optional[str],
        photo_bytes: Optional[bytes],
        photo_filename: str
    ) -> Optional[Message]:
        """Internal method to send a new system message."""
        try:
            if photo_bytes:
                input_file = BufferedInputFile(photo_bytes, filename=photo_filename)
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=input_file,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            elif photo:
                message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            else:
                message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
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
            logger.error(f"Failed to send new system message: {e}")
            return None
    
    async def _delete_message(self, chat_id: int, message_id: int) -> bool:
        """Safely delete a message, handling errors gracefully."""
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except TelegramBadRequest as e:
            if "message to delete not found" in str(e).lower():
                return True  # Already deleted
            if "message can't be deleted" in str(e).lower():
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
    
    # ============== Utility Methods (for backward compatibility) ==============
    
    async def send_ephemeral(self, *args, **kwargs) -> Optional[Message]:
        """Backward compatibility: alias for send_temporary."""
        return await self.send_temporary(*args, **kwargs)
    
    async def send_onetime(self, *args, **kwargs) -> Optional[Message]:
        """Backward compatibility: alias for send_regular."""
        return await self.send_regular(*args, **kwargs)
    
    async def delete_ephemeral(self, *args, **kwargs) -> int:
        """Backward compatibility: alias for delete_temporary."""
        return await self.delete_temporary(*args, **kwargs)
    
    async def answer_callback_and_delete(
        self,
        callback_query: CallbackQuery,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> None:
        """Answer callback query and delete the temporary message."""
        try:
            await callback_query.answer(text=text, show_alert=show_alert)
        except Exception as e:
            logger.error(f"Error answering callback: {e}")
        
        # Delete the message that had the callback button
        await self.delete_temporary(
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
        Cleans up temporary messages and sends/updates system message.
        """
        if cleanup_ephemeral:
            await self._delete_all_temporary(chat_id)
        
        return await self.send_system(chat_id, text, reply_markup, tag)
