"""
Type definitions for user-bot.

Uses TypedDict for strict typing of dictionaries and Protocol for service interfaces.
"""
from typing import TypedDict, Protocol, Optional, List


# ==============================================================
# Data Models (TypedDict for clarity and type checking)
# ==============================================================

class ChannelInfo(TypedDict):
    """Channel information dictionary."""
    success: bool
    channel_username: str
    channel_id: Optional[int]
    channel_title: Optional[str]
    message: str


class PostDataDict(TypedDict):
    """Post data dictionary."""
    telegram_message_id: int
    text: Optional[str]
    media_type: Optional[str]
    media_file_id: Optional[str]
    posted_at: str
    channel_telegram_id: Optional[int]  # Optional, may not be present in all contexts
    channel_username: Optional[str]  # Optional, may not be present in all contexts
    channel_title: Optional[str]  # Optional, may not be present in all contexts


class ScrapeResult(TypedDict):
    """Scrape result dictionary."""
    success: bool
    channel_username: str
    channel_telegram_id: Optional[int]
    channel_title: Optional[str]
    posts: List[PostDataDict]
    posts_count: int
    message: str


# ==============================================================
# Service Protocols (for dependency inversion and testing)
# ==============================================================

class TelethonServiceProtocol(Protocol):
    """Protocol for Telethon service interface."""
    
    async def connect(self) -> None:
        """Connect to Telegram."""
        ...
    
    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        ...
    
    async def ensure_connected(self) -> None:
        """Ensure client is connected."""
        ...
    
    async def join_channel(self, username: str) -> ChannelInfo:
        """Join a channel by username."""
        ...
    
    async def scrape_channel(self, username: str, limit: int) -> ScrapeResult:
        """Scrape recent messages from a channel."""
        ...
    
    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        ...


class MediaServiceProtocol(Protocol):
    """Protocol for media service interface."""
    
    async def download_photo(self, username: str, message_id: int) -> Optional[bytes]:
        """Download photo bytes for a specific channel message."""
        ...
    
    async def download_video(self, username: str, message_id: int) -> Optional[bytes]:
        """Download video bytes for a specific channel message."""
        ...


class SyncServiceProtocol(Protocol):
    """Protocol for sync service interface."""
    
    async def sync_channel(
        self,
        channel_telegram_id: int,
        channel_username: str,
        channel_title: str
    ) -> bool:
        """Sync channel data to core API."""
        ...
    
    async def sync_posts(
        self,
        channel_telegram_id: int,
        posts: List[PostDataDict]
    ) -> bool:
        """Sync posts to core API."""
        ...
    
    async def sync_realtime_post(
        self,
        channel_id: int,
        channel_username: str,
        channel_title: str,
        post_data: PostDataDict
    ) -> Optional[int]:
        """Sync a single post to core-api. Returns the created post_id."""
        ...


class NotificationServiceProtocol(Protocol):
    """Protocol for notification service interface."""
    
    async def notify_new_posts(
        self,
        channel_telegram_id: int,
        channel_username: str,
        channel_title: str,
        posts: List[PostDataDict]
    ) -> bool:
        """Notify main-bot about new posts via Redis."""
        ...
    
    async def notify_realtime_post(
        self,
        channel_id: int,
        channel_username: str,
        channel_title: str,
        post_data: PostDataDict,
        post_id: Optional[int] = None
    ) -> None:
        """Notify main-bot about new post via Redis."""
        ...

