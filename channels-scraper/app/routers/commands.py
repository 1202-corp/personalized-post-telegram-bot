"""
Command endpoints: scrape, join, refresh-channel-meta (same contract as user-bot).
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
from app.core.scraping import get_latest_posts, get_channel_info, download_media_url, search_posts
from app.core.config import get_settings
from app.services import SyncService
from app.services.sync_service import pseudo_telegram_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cmd", tags=["commands"])
settings = get_settings()


def _scraped_to_post_data(scraped: dict) -> dict:
    """Map scraped post dict to Core API post format. Content loaded on demand by message_id (/media/full)."""
    return {
        "telegram_message_id": scraped["id"],
        "text": scraped.get("text") or None,
        "media_type": scraped.get("media_type"),
        "posted_at": scraped.get("posted_at", ""),
    }


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_channel(request: ScrapeRequest):
    """Scrape channel via t.me; sync to Core API. Same contract as user-bot."""
    username = (request.channel_username or "").lstrip("@").strip()
    if not username:
        return ScrapeResponse(
            success=False,
            channel_username=request.channel_username,
            posts_count=0,
            message="channel_username required",
        )
    try:
        posts_raw = await get_latest_posts(username, limit=request.limit)
        if not posts_raw:
            return ScrapeResponse(
                success=True,
                channel_username=request.channel_username,
                posts_count=0,
                message="No posts found or channel not accessible",
            )
        channel_telegram_id = pseudo_telegram_id(username)
        info = await get_channel_info(username)
        channel_title = (info.get("title") or username) if info else username
        sync = SyncService()
        await sync.sync_channel(channel_telegram_id, username, channel_title)
        posts_data = [_scraped_to_post_data(p) for p in posts_raw]
        await sync.sync_posts(channel_telegram_id, posts_data, for_training=request.for_training)
        if info and info.get("avatar_url"):
            try:
                avatar_bytes = await download_media_url(info["avatar_url"])
                if avatar_bytes:
                    await sync.upload_channel_avatar(channel_telegram_id, avatar_bytes)
            except Exception as av_err:
                logger.debug("Avatar upload skipped: %s", av_err)
        if info and info.get("description") is not None:
            try:
                await sync.set_channel_description(channel_telegram_id, info["description"])
            except Exception as desc_err:
                logger.debug("Description set skipped: %s", desc_err)
        return ScrapeResponse(
            success=True,
            channel_username=request.channel_username,
            posts_count=len(posts_data),
            message=f"Scraped {len(posts_data)} posts",
        )
    except Exception as e:
        logger.exception("Scrape failed")
        return ScrapeResponse(
            success=False,
            channel_username=request.channel_username,
            posts_count=0,
            message=str(e),
        )


@router.post("/join", response_model=JoinChannelResponse)
async def join_channel(request: JoinChannelRequest):
    """Register channel in Core API (no real join; public channels only). Same contract as user-bot."""
    username = (request.channel_username or "").lstrip("@").strip()
    if not username:
        return JoinChannelResponse(
            success=False,
            channel_username=request.channel_username,
            channel_id=None,
            message="channel_username required",
        )
    try:
        channel_telegram_id = pseudo_telegram_id(username)
        info = await get_channel_info(username)
        channel_title = (info.get("title") or username) if info else username
        sync = SyncService()
        ok = await sync.sync_channel(channel_telegram_id, username, channel_title)
        if ok and info and info.get("avatar_url"):
            try:
                avatar_bytes = await download_media_url(info["avatar_url"])
                if avatar_bytes:
                    await sync.upload_channel_avatar(channel_telegram_id, avatar_bytes)
            except Exception:
                pass
        if ok and info and info.get("description") is not None:
            try:
                await sync.set_channel_description(channel_telegram_id, info["description"])
            except Exception:
                pass
        return JoinChannelResponse(
            success=ok,
            channel_username=request.channel_username,
            channel_id=channel_telegram_id,
            message="Channel registered" if ok else "Failed to register",
        )
    except Exception as e:
        logger.exception("Join failed")
        return JoinChannelResponse(
            success=False,
            channel_username=request.channel_username,
            channel_id=None,
            message=str(e),
        )


@router.post("/refresh-channel-meta", response_model=RefreshChannelMetaResponse)
async def refresh_channel_meta(request: RefreshChannelMetaRequest):
    """Refresh channel avatar and description from t.me; push to Core API."""
    username = (request.channel_username or "").lstrip("@").strip()
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
        channel_telegram_id = pseudo_telegram_id(username)
        info = await get_channel_info(username)
        if not info:
            return RefreshChannelMetaResponse(
                success=False,
                channel_username=request.channel_username,
                channel_telegram_id=None,
                description_set=False,
                avatar_uploaded=False,
                message="Channel not found or not accessible",
            )
        sync = SyncService()
        description_set = False
        avatar_uploaded = False
        if info.get("description") is not None:
            description_set = await sync.set_channel_description(
                channel_telegram_id, info["description"]
            )
        if info.get("avatar_url"):
            avatar_bytes = await download_media_url(info["avatar_url"])
            if avatar_bytes:
                avatar_uploaded = await sync.upload_channel_avatar(
                    channel_telegram_id, avatar_bytes
                )
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


@router.get("/search")
async def search_channel_posts(
    channel_username: str,
    query: str,
    limit: int = 20,
):
    """
    Search posts by text in channel. Scans posts from feed (up to 200), returns matches.
    Query params: channel_username, query, limit (default 20).
    """
    if not (channel_username or "").strip():
        raise HTTPException(status_code=400, detail="channel_username required")
    if not (query or "").strip():
        raise HTTPException(status_code=400, detail="query required")
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be 1..100")
    try:
        posts = await search_posts(
            channel_username.strip().lstrip("@"),
            query=query.strip(),
            limit=limit,
        )
        return {
            "channel_username": channel_username,
            "query": query,
            "count": len(posts),
            "posts": [
                {
                    "message_id": p["id"],
                    "text": (p.get("text") or "")[:500],
                    "date": p.get("date"),
                    "posted_at": p.get("posted_at"),
                    "has_photo": bool(p.get("first_photo_url") or (p.get("media") and len(p.get("media", [])) > 0)),
                    "media_type": p.get("media_type"),
                }
                for p in posts
            ],
        }
    except Exception as e:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=str(e))
