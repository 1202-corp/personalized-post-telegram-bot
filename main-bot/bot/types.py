"""
Type definitions for the bot using TypedDict and Protocol.

This module provides type safety for all data structures used throughout the bot.
"""

from typing import TypedDict, Protocol, Optional, List, Dict, Any
from datetime import datetime


# ============== Data Models ==============

class PostData(TypedDict, total=False):
    """Post data structure from API."""
    id: int
    text: Optional[str]
    channel_username: str
    channel_title: str
    telegram_message_id: Optional[int]
    media_type: Optional[str]  # "photo", "video", None
    media_file_id: Optional[str]
    relevance_score: Optional[float]
    created_at: Optional[str]


class ChannelData(TypedDict, total=False):
    """Channel data structure from API."""
    id: int
    username: str
    title: str
    is_for_training: bool
    is_bonus: bool
    created_at: Optional[str]


class UserData(TypedDict, total=False):
    """User data structure from API."""
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    status: str
    is_trained: bool
    bonus_channels_count: int
    initial_best_post_sent: bool
    language: Optional[str]
    created_at: Optional[str]


class InteractionData(TypedDict, total=False):
    """Interaction data structure from API."""
    id: int
    user_telegram_id: int
    post_id: int
    interaction_type: str  # "like", "dislike"
    created_at: Optional[str]


class TrainingState(TypedDict, total=False):
    """FSM state data for training flow."""
    training_posts: List[PostData]
    current_post_index: int
    rated_count: int
    user_id: int
    is_bonus_training: bool
    is_retrain: bool
    channel_usernames: List[str]


class FeedState(TypedDict, total=False):
    """FSM state data for feed operations."""
    feed_posts: List[PostData]
    current_post_index: int
    user_id: int


# ============== Service Protocols ==============

class APIServiceProtocol(Protocol):
    """Protocol for API service clients."""
    
    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None
    ) -> Optional[UserData]:
        """Get or create a user."""
        ...
    
    async def get_user(self, telegram_id: int) -> Optional[UserData]:
        """Get user by telegram ID."""
        ...
    
    async def update_user(
        self,
        telegram_id: int,
        status: Optional[str] = None,
        user_role: Optional[str] = None,
        bonus_channels_count: Optional[int] = None,
        initial_best_post_sent: Optional[bool] = None,
    ) -> Optional[UserData]:
        """Update user fields."""
        ...
    
    async def get_training_posts(
        self,
        telegram_id: int,
        channel_usernames: List[str],
        posts_per_channel: int = 7
    ) -> List[PostData]:
        """Get posts for training."""
        ...
    
    async def get_best_posts(
        self,
        telegram_id: int,
        limit: int = 1
    ) -> List[PostData]:
        """Get best posts for user feed."""
        ...
    
    async def create_interaction(
        self,
        telegram_id: int,
        post_id: int,
        interaction_type: str
    ) -> bool:
        """Create a user interaction with a post."""
        ...
    
    async def train_model(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Trigger model training for user."""
        ...


class MediaServiceProtocol(Protocol):
    """Protocol for media service (prefetch, cache, download)."""
    
    async def prefetch_post_media(
        self,
        chat_id: int,
        post: PostData
    ) -> None:
        """Prefetch media for a single post."""
        ...
    
    async def prefetch_posts_media(
        self,
        chat_id: int,
        posts: List[PostData],
        start_index: int,
        count: int = 5
    ) -> None:
        """Prefetch media for multiple posts."""
        ...
    
    async def get_cached_photo(
        self,
        chat_id: int,
        post_id: int
    ) -> Optional[bytes]:
        """Get cached photo bytes for a post."""
        ...
    
    async def get_cached_video(
        self,
        chat_id: int,
        post_id: int
    ) -> Optional[bytes]:
        """Get cached video bytes for a post."""
        ...
    
    async def clear_cache(self, chat_id: Optional[int] = None) -> None:
        """Clear media cache for a chat or all chats."""
        ...


class PostServiceProtocol(Protocol):
    """Protocol for post sending service."""
    
    async def send_post(
        self,
        chat_id: int,
        post: PostData,
        keyboard: Optional[Any] = None,  # InlineKeyboardMarkup
        tag: str = "post",
        message_type: str = "ephemeral",
        include_relevance: bool = False,
    ) -> tuple[bool, List[int]]:
        """
        Send a post with optional media.
        
        Returns:
            Tuple of (sent_with_caption: bool, media_message_ids: List[int])
        """
        ...


class UserBotServiceProtocol(Protocol):
    """Protocol for user-bot service (scraper)."""
    
    async def scrape_channel(
        self,
        channel_username: str,
        limit: int = 7
    ) -> Optional[Dict[str, Any]]:
        """Trigger channel scraping."""
        ...
    
    async def join_channel(self, channel_username: str) -> Optional[Dict[str, Any]]:
        """Request user-bot to join a channel."""
        ...
    
    async def get_photo(
        self,
        channel_username: str,
        message_id: int
    ) -> Optional[bytes]:
        """Fetch photo bytes for a specific channel message."""
        ...
    
    async def get_video(
        self,
        channel_username: str,
        message_id: int
    ) -> Optional[bytes]:
        """Fetch video bytes for a specific channel message."""
        ...
    
    async def get_post_text(
        self,
        channel_username: str,
        message_id: int
    ) -> Optional[str]:
        """Fetch post text in HTML format for a specific channel message."""
        ...

