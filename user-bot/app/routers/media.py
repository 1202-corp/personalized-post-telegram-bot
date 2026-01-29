"""
Media download endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException, Response

from app.services import get_telethon_service, MediaService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/photo")
async def get_photo(channel_username: str, message_id: int):
    """
    Return photo bytes for a given channel message.
    
    This endpoint is used by main-bot to display photos for posts.
    
    Args:
        channel_username: Channel username (with or without @)
        message_id: Telegram message ID
        
    Returns:
        Photo bytes as JPEG image
        
    Raises:
        HTTPException: 503 if Telethon not connected, 404 if photo not found
    """
    telethon_service = get_telethon_service()
    
    if not telethon_service.is_connected:
        raise HTTPException(status_code=503, detail="Telethon client not connected")
    
    media_service = MediaService(telethon_service)
    data = await media_service.download_photo(channel_username, message_id)
    
    if not data:
        raise HTTPException(status_code=404, detail="Photo not found")
    
    return Response(content=data, media_type="image/jpeg")


@router.get("/video")
async def get_video(channel_username: str, message_id: int):
    """
    Return video bytes for a given channel message.
    
    This endpoint is used by main-bot to display videos for posts.
    
    Args:
        channel_username: Channel username (with or without @)
        message_id: Telegram message ID
        
    Returns:
        Video bytes as MP4 video
        
    Raises:
        HTTPException: 503 if Telethon not connected, 404 if video not found
    """
    telethon_service = get_telethon_service()
    
    if not telethon_service.is_connected:
        raise HTTPException(status_code=503, detail="Telethon client not connected")
    
    media_service = MediaService(telethon_service)
    data = await media_service.download_video(channel_username, message_id)
    
    if not data:
        raise HTTPException(status_code=404, detail="Video not found")
    
    return Response(content=data, media_type="video/mp4")


@router.get("/text")
async def get_post_text(channel_username: str, message_id: int):
    """
    Return post text in HTML format for a given channel message.
    
    This endpoint is used by main-bot to get post text during training.
    According to the plan, post text should not be stored in DB during scraping,
    but fetched on-demand from user-bot when training starts.
    
    Args:
        channel_username: Channel username (with or without @)
        message_id: Telegram message ID
        
    Returns:
        JSON response with HTML formatted text
        
    Raises:
        HTTPException: 503 if Telethon not connected, 404 if text not found
    """
    telethon_service = get_telethon_service()
    
    if not telethon_service.is_connected:
        raise HTTPException(status_code=503, detail="Telethon client not connected")
    
    media_service = MediaService(telethon_service)
    text = await media_service.get_post_text(channel_username, message_id)
    
    if text is None:
        raise HTTPException(status_code=404, detail="Post text not found")
    
    return {"text": text}


@router.get("/full")
async def get_post_full_content(channel_username: str, message_id: int):
    """
    Return full post content (text and media) for a given channel message.
    
    This endpoint is used by main-bot to get post content for caching in Redis.
    Returns text (HTML) and media (base64 encoded) if available.
    
    Args:
        channel_username: Channel username (with or without @)
        message_id: Telegram message ID
        
    Returns:
        JSON response with text, media_type, and media_data (base64)
        
    Raises:
        HTTPException: 503 if Telethon not connected, 404 if post not found
    """
    telethon_service = get_telethon_service()
    
    if not telethon_service.is_connected:
        raise HTTPException(status_code=503, detail="Telethon client not connected")
    
    media_service = MediaService(telethon_service)
    content = await media_service.get_post_full_content(channel_username, message_id)
    
    if content is None:
        raise HTTPException(status_code=404, detail="Post content not found")
    
    return content

