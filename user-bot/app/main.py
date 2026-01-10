"""
User-bot FastAPI application.
Exposes HTTP endpoints for the scraper commands.
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
import httpx

from app.config import get_settings
from app.telethon_client import get_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()


# ============== Request/Response Models ==============

class ScrapeRequest(BaseModel):
    channel_username: str
    limit: int = 7


class ScrapeResponse(BaseModel):
    success: bool
    channel_username: str
    posts_count: int
    message: str


class JoinChannelRequest(BaseModel):
    channel_username: str


class JoinChannelResponse(BaseModel):
    success: bool
    channel_username: str
    channel_id: Optional[int] = None
    message: str


class PostData(BaseModel):
    telegram_message_id: int
    text: Optional[str] = None
    media_type: Optional[str] = None
    media_file_id: Optional[str] = None
    posted_at: str


class BulkPostCreate(BaseModel):
    channel_telegram_id: int
    posts: List[PostData]


# ============== Application Lifespan ==============

_background_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    global _background_task
    
    # Startup
    client = get_client()
    try:
        await client.connect()
        logger.info("Telethon client started with real-time event handler")
        
        # Auto-join default training channels for real-time events
        default_channels = settings.default_training_channels
        if default_channels:
            channels = [c.strip().lstrip("@") for c in default_channels.split(",") if c.strip()]
            for channel in channels:
                try:
                    await client.join_channel(channel)
                    logger.info(f"Auto-joined default channel: @{channel}")
                except Exception as e:
                    logger.warning(f"Failed to auto-join @{channel}: {e}")
    except Exception as e:
        logger.error(f"Failed to start Telethon client: {e}")
    
    yield
    
    # Shutdown
    if _background_task:
        _background_task.cancel()
    await client.disconnect()
    logger.info("Telethon client stopped")


app = FastAPI(
    title="User Bot - Scraper Service",
    description="Telethon-based scraper for Telegram channels",
    version="1.0.0",
    lifespan=lifespan,
)


# ============== Helper Functions ==============

async def sync_channel_to_core_api(
    channel_telegram_id: int,
    channel_username: str,
    channel_title: str
) -> bool:
    """Sync channel data to core API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.core_api_url}/api/v1/channels/",
                json={
                    "telegram_id": channel_telegram_id,
                    "username": channel_username,
                    "title": channel_title,
                    "is_default": False,
                }
            )
            return response.status_code in [200, 201]
    except Exception as e:
        logger.error(f"Failed to sync channel to core API: {e}")
        return False


async def notify_to_redis(
    channel_telegram_id: int,
    channel_username: str,
    channel_title: str,
    posts: list
) -> bool:
    """Notify main-bot about new posts via Redis for real-time delivery."""
    if not posts:
        return True
    
    try:
        import json
        import redis.asyncio as aioredis
        
        redis_client = aioredis.from_url("redis://redis:6379/0")
        
        # Send each new post as an event
        for post in posts:
            event_data = {
                "channel_telegram_id": channel_telegram_id,
                "channel_username": channel_username,
                "channel_title": channel_title,
                "telegram_message_id": post["telegram_message_id"],
                "text": post.get("text"),
                "media_type": post.get("media_type"),
                "media_file_id": post.get("media_file_id"),
                "posted_at": post["posted_at"],
            }
            await redis_client.publish("ppb:new_posts", json.dumps(event_data))
        
        await redis_client.close()
        logger.info(f"Notified main-bot about {len(posts)} new posts from {channel_username}")
        return True
    except Exception as e:
        logger.error(f"Failed to notify about new posts: {e}")
        return False


async def sync_posts_to_core_api(
    channel_telegram_id: int,
    posts: list
) -> bool:
    """Sync posts to core API."""
    if not posts:
        return True
    
    try:
        post_data = []
        for post in posts:
            post_data.append({
                "telegram_message_id": post["telegram_message_id"],
                "text": post.get("text"),
                "media_type": post.get("media_type"),
                "media_file_id": post.get("media_file_id"),
                "posted_at": post["posted_at"],
            })
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.core_api_url}/api/v1/posts/bulk",
                json={
                    "channel_telegram_id": channel_telegram_id,
                    "posts": post_data,
                }
            )
            return response.status_code in [200, 201]
    except Exception as e:
        logger.error(f"Failed to sync posts to core API: {e}")
        return False


# ============== Endpoints ==============

@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "user-bot"}


@app.get("/health/ready")
async def readiness_check():
    """Readiness check - verifies Telethon and core-api are available."""
    client = get_client()
    checks = {
        "service": "user-bot",
        "telethon": "unknown",
        "core_api": "unknown",
    }
    all_healthy = True
    
    # Check Telethon
    if client.is_connected:
        checks["telethon"] = "healthy"
    else:
        checks["telethon"] = "unhealthy: not connected"
        all_healthy = False
    
    # Check core-api
    try:
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            response = await http_client.get(f"{settings.core_api_url}/health")
            if response.status_code == 200:
                checks["core_api"] = "healthy"
            else:
                checks["core_api"] = f"unhealthy: status {response.status_code}"
                all_healthy = False
    except Exception as e:
        checks["core_api"] = f"unhealthy: {str(e)[:50]}"
        all_healthy = False
    
    checks["status"] = "healthy" if all_healthy else "degraded"
    return checks


@app.post("/cmd/scrape", response_model=ScrapeResponse)
async def scrape_channel(request: ScrapeRequest):
    """
    Scrape messages from a Telegram channel.
    This endpoint is called by main-bot to trigger scraping.
    """
    client = get_client()
    
    if not client.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Telethon client not connected"
        )
    
    # Scrape the channel
    result = await client.scrape_channel(
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
    await sync_channel_to_core_api(
        result["channel_telegram_id"],
        result["channel_username"],
        result["channel_title"]
    )
    
    # Sync posts to core API
    await sync_posts_to_core_api(
        result["channel_telegram_id"],
        result["posts"]
    )
    
    # NOTE: Do NOT notify via Redis here - scrape is for training/historical posts
    # Real-time notifications happen only via Telethon event handler for NEW posts
    
    return ScrapeResponse(
        success=True,
        channel_username=request.channel_username,
        posts_count=result["posts_count"],
        message=result["message"]
    )


@app.post("/cmd/join", response_model=JoinChannelResponse)
async def join_channel(request: JoinChannelRequest):
    """
    Join a Telegram channel.
    This endpoint is called by main-bot to join channels.
    """
    client = get_client()
    
    if not client.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Telethon client not connected"
        )
    
    # Join the channel
    result = await client.join_channel(request.channel_username)
    
    if result["success"]:
        # Sync channel to core API
        await sync_channel_to_core_api(
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


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "User Bot - Scraper Service",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/media/photo")
async def get_photo(channel_username: str, message_id: int):
    """Return photo bytes for a given channel message.

    This endpoint is used by main-bot to display photos for posts.
    """
    client = get_client()

    if not client.is_connected:
        raise HTTPException(status_code=503, detail="Telethon client not connected")

    data = await client.download_photo(channel_username, message_id)
    if not data:
        raise HTTPException(status_code=404, detail="Photo not found")

    return Response(content=data, media_type="image/jpeg")


@app.get("/media/video")
async def get_video(channel_username: str, message_id: int):
    """Return video bytes for a given channel message.

    This endpoint is used by main-bot to display videos for posts.
    """
    client = get_client()

    if not client.is_connected:
        raise HTTPException(status_code=503, detail="Telethon client not connected")

    data = await client.download_video(channel_username, message_id)
    if not data:
        raise HTTPException(status_code=404, detail="Video not found")

    return Response(content=data, media_type="video/mp4")
