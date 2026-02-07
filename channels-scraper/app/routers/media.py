"""
Media endpoints: photo, video, text, full (same contract as user-bot).
"""
import base64
import logging
from fastapi import APIRouter, HTTPException, Response

from app.core.scraping import get_post, download_media_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/media", tags=["media"])


@router.get("/photo")
async def get_photo(channel_username: str, message_id: int):
    """Return photo bytes for channel message. Same contract as user-bot."""
    post = await get_post(channel_username, message_id)
    if not post:
        raise HTTPException(status_code=404, detail="Photo not found")
    url = post.get("first_photo_url") or post.get("first_media_url")
    if not url or post.get("media_type") != "photo":
        raise HTTPException(status_code=404, detail="Photo not found")
    data = await download_media_url(url)
    if not data:
        raise HTTPException(status_code=404, detail="Photo not found")
    return Response(content=data, media_type="image/jpeg")


@router.get("/video")
async def get_video(channel_username: str, message_id: int):
    """Return video as JPEG (thumbnail). Same contract as user-bot (main-bot expects JPEG)."""
    post = await get_post(channel_username, message_id)
    if not post:
        raise HTTPException(status_code=404, detail="Video not found")
    url = post.get("video_url") or post.get("first_media_url")
    if not url:
        thumb_url = post.get("first_photo_url")
        if thumb_url:
            data = await download_media_url(thumb_url)
            if data:
                return Response(content=data, media_type="image/jpeg")
        raise HTTPException(status_code=404, detail="Video not found")
    data = await download_media_url(url)
    if not data:
        thumb_url = post.get("first_photo_url")
        if thumb_url:
            data = await download_media_url(thumb_url)
        if not data:
            raise HTTPException(status_code=404, detail="Video not found")
    return Response(content=data, media_type="image/jpeg")


@router.get("/text")
async def get_post_text(channel_username: str, message_id: int):
    """Return post text (HTML). Same contract as user-bot."""
    post = await get_post(channel_username, message_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post text not found")
    text = post.get("text") or ""
    return {"text": text}


@router.get("/full")
async def get_post_full_content(channel_username: str, message_id: int):
    """Return full post: text, media_type, media_data (base64). Same contract as user-bot."""
    post = await get_post(channel_username, message_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post content not found")
    text = post.get("text") or ""
    media_type = post.get("media_type")
    media_data = None
    url = post.get("first_photo_url") or post.get("first_media_url")
    if url:
        data = await download_media_url(url)
        if data:
            media_data = base64.b64encode(data).decode("utf-8")
    return {
        "text": text,
        "media_type": media_type,
        "media_data": media_data,
    }
