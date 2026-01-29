"""
Command endpoints for scraping and joining channels.
"""
import logging
from fastapi import APIRouter, HTTPException

from app.schemas import ScrapeRequest, ScrapeResponse, JoinChannelRequest, JoinChannelResponse
from app.services import get_telethon_service, SyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cmd", tags=["commands"])


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_channel(request: ScrapeRequest):
    """
    Scrape messages from a Telegram channel.
    
    This endpoint is called by main-bot to trigger scraping.
    Scraped posts are synced to Core API but NOT notified via Redis
    (real-time notifications happen only via Telethon event handler for NEW posts).
    
    Args:
        request: ScrapeRequest with channel_username and limit
        
    Returns:
        ScrapeResponse with success status and posts count
        
    Raises:
        HTTPException: 503 if Telethon client not connected
    """
    telethon_service = get_telethon_service()
    
    if not telethon_service.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Telethon client not connected"
        )
    
    # Scrape the channel
    result = await telethon_service.scrape_channel(
        request.channel_username,
        request.limit
    )
    
    if not result["success"]:
        return ScrapeResponse(
            success=False,
            channel_username=request.channel_username,
            posts_count=0,
            message=result["message"]
        )
    
    # Sync channel to core API
    sync_service = SyncService()
    await sync_service.sync_channel(
        result["channel_telegram_id"],
        result["channel_username"],
        result["channel_title"]
    )
    
    # Sync posts to core API
    # For training posts, don't store text (only metadata) - text will be fetched on-demand
    await sync_service.sync_posts(
        result["channel_telegram_id"],
        result["posts"],
        for_training=request.for_training
    )
    
    # NOTE: Do NOT notify via Redis here - scrape is for training/historical posts
    # Real-time notifications happen only via Telethon event handler for NEW posts
    
    return ScrapeResponse(
        success=True,
        channel_username=request.channel_username,
        posts_count=result["posts_count"],
        message=result["message"]
    )


@router.post("/join", response_model=JoinChannelResponse)
async def join_channel(request: JoinChannelRequest):
    """
    Join a Telegram channel.
    
    This endpoint is called by main-bot to join channels.
    After joining, channel data is synced to Core API.
    
    Args:
        request: JoinChannelRequest with channel_username
        
    Returns:
        JoinChannelResponse with success status and channel info
        
    Raises:
        HTTPException: 503 if Telethon client not connected
    """
    telethon_service = get_telethon_service()
    
    if not telethon_service.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Telethon client not connected"
        )
    
    # Join the channel
    result = await telethon_service.join_channel(request.channel_username)
    
    if result["success"]:
        # Sync channel to core API
        sync_service = SyncService()
        await sync_service.sync_channel(
            result["channel_id"],
            result["channel_username"],
            result.get("channel_title", "Unknown")
        )
    
    return JoinChannelResponse(
        success=result["success"],
        channel_username=result["channel_username"],
        channel_id=result.get("channel_id"),
        message=result["message"]
    )

