"""
User-bot FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.services import get_telethon_service, SyncService, NotificationService, EventHandlerService
from app.routers import commands, media, health

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    telethon_service = get_telethon_service()
    try:
        await telethon_service.connect()
        logger.info("Telethon client started")
        
        # Initialize services
        sync_service = SyncService()
        notification_service = NotificationService()
        event_handler_service = EventHandlerService(
            telethon_service,
            sync_service,
            notification_service
        )
        
        # Register event handler for real-time post detection
        await event_handler_service.register_event_handler()
        logger.info("Real-time event handler registered")
        
        # Auto-join default training channels for real-time events
        default_channels = settings.default_training_channels
        if default_channels:
            channels = [c.strip().lstrip("@") for c in default_channels.split(",") if c.strip()]
            for channel in channels:
                try:
                    await telethon_service.join_channel(channel)
                    logger.info(f"Auto-joined default channel: @{channel}")
                except Exception as e:
                    logger.warning(f"Failed to auto-join @{channel}: {e}")
    except Exception as e:
        logger.error(f"Failed to start Telethon client: {e}")
    
    yield
    
    # Shutdown
    await telethon_service.disconnect()
    logger.info("Telethon client stopped")


app = FastAPI(
    title="User Bot - Scraper Service",
    description="Telethon-based scraper for Telegram channels",
    version="1.0.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(health.router)
app.include_router(commands.router)
app.include_router(media.router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "User Bot - Scraper Service",
        "docs": "/docs",
        "health": "/health"
    }
