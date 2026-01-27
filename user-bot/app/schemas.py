"""
Pydantic schemas for request/response models.
"""
from typing import Optional, List
from pydantic import BaseModel


class ScrapeRequest(BaseModel):
    """Request schema for scraping a channel."""
    channel_username: str
    limit: int = 7


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

