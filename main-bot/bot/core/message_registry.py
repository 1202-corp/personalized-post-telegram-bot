"""
Message registry for tracking messages per chat.

Thread-safe registry implementation using asyncio.Lock.
"""

import asyncio
from enum import Enum
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime


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

