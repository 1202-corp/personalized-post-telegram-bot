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

