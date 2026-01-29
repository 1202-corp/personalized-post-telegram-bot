"""
Pydantic schemas for request/response models.
"""
from typing import Optional, List
from pydantic import BaseModel


class ScrapeRequest(BaseModel):
    """Request schema for scraping a channel."""
    channel_username: str
    limit: int = 7
    for_training: bool = False  # If True, don't store text in DB (only metadata)


class ScrapeResponse(BaseModel):
    """Response schema for scraping operation."""
    success: bool
    channel_username: str
    posts_count: int
    message: str


class JoinChannelRequest(BaseModel):
    """Request schema for joining a channel."""
    channel_username: str


class JoinChannelResponse(BaseModel):
    """Response schema for join channel operation."""
    success: bool
    channel_username: str
    channel_id: Optional[int] = None
    message: str


class RefreshChannelMetaRequest(BaseModel):
    """Request schema for refreshing channel avatar and description (backfill)."""
    channel_username: str


class RefreshChannelMetaResponse(BaseModel):
    """Response schema for refresh channel meta."""
    success: bool
    channel_username: str
    channel_telegram_id: Optional[int] = None
    description_set: bool
    avatar_uploaded: bool
    message: str


class PostData(BaseModel):
    """Post data schema."""
    telegram_message_id: int
    text: Optional[str] = None
    media_type: Optional[str] = None
    media_file_id: Optional[str] = None
    posted_at: str


class BulkPostCreate(BaseModel):
    """Bulk post create schema."""
    channel_telegram_id: int
    posts: List[PostData]

