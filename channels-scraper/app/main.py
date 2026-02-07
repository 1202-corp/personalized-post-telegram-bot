"""
Channels-scraper FastAPI app: web-scraping based (t.me), no Telethon.
Same HTTP API as user-bot for compatibility with main-bot and Core API.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.routers import commands, media, health
from app.services import SyncService, NotificationService
from app.core.scraping import get_post, get_latest_posts
from app.services.sync_service import pseudo_telegram_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()

_poll_task: asyncio.Task | None = None


def _scraped_to_post_data(scraped: dict) -> dict:
    return {
        "telegram_message_id": scraped["id"],
        "text": scraped.get("text") or None,
        "media_type": scraped.get("media_type"),
        "posted_at": scraped.get("posted_at", ""),
    }


async def _poll_loop() -> None:
    """Periodically check all channels for new posts; sync and notify."""
    sync = SyncService()
    notification = NotificationService()
    last_seen: dict[str, int] = {}  # channel_username -> last post_id seen
    while True:
        try:
            await asyncio.sleep(settings.poll_interval_sec)
            channels = await sync.list_channels(skip=0, limit=500)
            for ch in channels:
                username = (ch.get("username") or "").strip().lower()
                if not username:
                    continue
                try:
                    posts_raw = await get_latest_posts(username, limit=3)
                    if not posts_raw:
                        continue
                    channel_telegram_id = ch.get("telegram_id") or pseudo_telegram_id(username)
                    channel_title = ch.get("title") or username
                    prev = last_seen.get(username, 0)
                    for p in posts_raw:
                        post_id = p["id"]
                        if post_id > prev:
                            post_data = _scraped_to_post_data(p)
                            post_id_db = await sync.sync_realtime_post(
                                channel_telegram_id,
                                username,
                                channel_title,
                                post_data,
                            )
                            await notification.notify_realtime_post(
                                channel_telegram_id,
                                username,
                                channel_title,
                                post_data,
                                post_id=post_id_db,
                            )
                    if posts_raw:
                        last_seen[username] = max(p["id"] for p in posts_raw)
                except Exception as e:
                    logger.warning("Poll channel @%s: %s", username, e)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Poll loop error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: start poll task. Shutdown: cancel it."""
    global _poll_task
    _poll_task = asyncio.create_task(_poll_loop())
    logger.info("Poll loop started (interval=%ss)", settings.poll_interval_sec)
    yield
    if _poll_task:
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
    logger.info("Poll loop stopped")


app = FastAPI(
    title="Channels Scraper - Web Scraper Service",
    description="t.me web-scraping based scraper (no Telethon); same API as user-bot",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(commands.router)
app.include_router(media.router)


@app.get("/")
async def root():
    return {
        "message": "Channels Scraper - Web Scraper Service",
        "docs": "/docs",
        "health": "/health",
    }
