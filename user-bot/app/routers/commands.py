"""
Command endpoints for scraping and joining channels.
"""
import logging
from fastapi import APIRouter, HTTPException

from app.schemas import (
    ScrapeRequest,
    ScrapeResponse,
    JoinChannelRequest,
    JoinChannelResponse,
    RefreshChannelMetaRequest,
    RefreshChannelMetaResponse,
)
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
    # Sync channel avatar and description (so they appear without waiting for a new post)
    try:
        avatar_bytes = await telethon_service.get_channel_avatar_bytes(result["channel_username"])
        if avatar_bytes:
            await sync_service.upload_channel_avatar(result["channel_telegram_id"], avatar_bytes)
    except Exception as av_err:
        logger.debug("Channel avatar upload skipped after scrape: %s", av_err)
    try:
        description = await telethon_service.get_channel_description(result["channel_username"])
        await sync_service.set_channel_description(result["channel_telegram_id"], description)
    except Exception as desc_err:
        logger.debug("Channel description upload skipped after scrape: %s", desc_err)
    
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
        # Sync channel avatar and description
        try:
            avatar_bytes = await telethon_service.get_channel_avatar_bytes(result["channel_username"])
            if avatar_bytes:
                await sync_service.upload_channel_avatar(result["channel_id"], avatar_bytes)
        except Exception as av_err:
            logger.debug("Channel avatar upload skipped after join: %s", av_err)
        try:
            description = await telethon_service.get_channel_description(result["channel_username"])
            await sync_service.set_channel_description(result["channel_id"], description)
        except Exception as desc_err:
            logger.debug("Channel description upload skipped after join: %s", desc_err)
    
    return JoinChannelResponse(
        success=result["success"],
        channel_username=result["channel_username"],
        channel_id=result.get("channel_id"),
        message=result["message"]
    )


@router.post("/refresh-channel-meta", response_model=RefreshChannelMetaResponse)
async def refresh_channel_meta(request: RefreshChannelMetaRequest):
    """
    Refresh channel avatar and description from Telegram and push to Core API.
    Use this to backfill existing channels without re-adding them.
    """
    telethon_service = get_telethon_service()
    if not telethon_service.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Telethon client not connected"
        )
    username = (request.channel_username or "").lstrip("@")
    if not username:
        return RefreshChannelMetaResponse(
            success=False,
            channel_username=request.channel_username,
            channel_telegram_id=None,
            description_set=False,
            avatar_uploaded=False,
            message="channel_username required",
        )
    try:
        entity = await telethon_service._get_channel_entity(username)
        if not entity:
            return RefreshChannelMetaResponse(
                success=False,
                channel_username=request.channel_username,
                channel_telegram_id=None,
                description_set=False,
                avatar_uploaded=False,
                message="Channel not found or not accessible",
            )
        channel_telegram_id = entity.id
        sync_service = SyncService()
        description_set = False
        avatar_uploaded = False
        try:
            description = await telethon_service.get_channel_description(username)
            ok = await sync_service.set_channel_description(channel_telegram_id, description)
            description_set = ok
        except Exception as e:
            logger.debug("refresh_channel_meta description: %s", e)
        try:
            avatar_bytes = await telethon_service.get_channel_avatar_bytes(username)
            if avatar_bytes:
                avatar_uploaded = await sync_service.upload_channel_avatar(
                    channel_telegram_id, avatar_bytes
                )
        except Exception as e:
            logger.debug("refresh_channel_meta avatar: %s", e)
        return RefreshChannelMetaResponse(
            success=True,
            channel_username=request.channel_username,
            channel_telegram_id=channel_telegram_id,
            description_set=description_set,
            avatar_uploaded=avatar_uploaded,
            message="OK",
        )
    except Exception as e:
        logger.exception("refresh_channel_meta failed")
        return RefreshChannelMetaResponse(
            success=False,
            channel_username=request.channel_username,
            channel_telegram_id=None,
            description_set=False,
            avatar_uploaded=False,
            message=str(e),
        )

