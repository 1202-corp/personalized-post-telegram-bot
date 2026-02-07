"""
Pydantic schemas for request/response (same contract as user-bot).
"""
from typing import Optional
from pydantic import BaseModel, Field


class ScrapeRequest(BaseModel):
    """Request for scraping a channel."""
    channel_username: str
    limit: int = Field(default=7, ge=1, le=200, description="Max posts to fetch (feed page ~20, cap 200)")
    for_training: bool = False


class ScrapeResponse(BaseModel):
    """Response from scrape."""
    success: bool
    channel_username: str
    posts_count: int
    message: str


class JoinChannelRequest(BaseModel):
    """Request to join (register) a channel."""
    channel_username: str


class JoinChannelResponse(BaseModel):
    """Response from join."""
    success: bool
    channel_username: str
    channel_id: Optional[int] = None
    message: str


class RefreshChannelMetaRequest(BaseModel):
    """Request to refresh channel avatar and description."""
    channel_username: str


class RefreshChannelMetaResponse(BaseModel):
    """Response from refresh-channel-meta."""
    success: bool
    channel_username: str
    channel_telegram_id: Optional[int] = None
    description_set: bool
    avatar_uploaded: bool
    message: str
