"""
Main entry point for the Telegram bot.
"""

import asyncio
import os
import redis.asyncio as redis
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import get_settings
from bot.logging_config import setup_logging, get_logger
from bot.message_manager import MessageManager
from bot.retention import RetentionService
from bot.api_client import close_clients
from bot.handlers import commands, training, feed

# Configure logging
setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    log_dir=os.getenv("LOG_DIR", "/var/log/ppb"),
    log_file="main-bot.log",
)
logger = get_logger(__name__)

settings = get_settings()

# Redis heartbeat
redis_client = None
heartbeat_task = None

async def heartbeat_loop():
    """Send heartbeat to Redis every 30 seconds."""
    global redis_client
    try:
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/1"))
        while True:
            try:
                await redis_client.set("ppb:main_bot:heartbeat", "alive", ex=60)
                await redis_client.set("ppb:main_bot:last_seen", str(int(asyncio.get_event_loop().time())), ex=120)
            except Exception as e:
                logger.warning(f"Heartbeat error: {e}")
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        pass
    finally:
        if redis_client:
            await redis_client.close()


async def main():
    """Main function to run the bot."""
    # Initialize bot with default properties
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    
    # Initialize dispatcher with memory storage
    # In production, use Redis storage for persistence
    dp = Dispatcher(storage=MemoryStorage())
    
    # Initialize message manager
    message_manager = MessageManager(bot)
    
    # Initialize retention service
    retention_service = RetentionService(bot, message_manager)
    
    # Register routers
    dp.include_router(commands.router)
    dp.include_router(training.router)
    dp.include_router(feed.router)
    
    # Middleware to inject message_manager into handlers
    @dp.update.outer_middleware()
    async def inject_message_manager(handler, event, data):
        data["message_manager"] = message_manager
        return await handler(event, data)
    
    # Startup event
    async def on_startup():
        global heartbeat_task
        logger.info("Bot starting up...")
        await retention_service.start()
        # Start heartbeat
        heartbeat_task = asyncio.create_task(heartbeat_loop())
        # Set bot commands
        from aiogram.types import BotCommand
        await bot.set_my_commands([
            BotCommand(command="start", description="Start the bot"),
            BotCommand(command="help", description="Show help"),
            BotCommand(command="status", description="Check your status"),
            BotCommand(command="reset", description="Clean up messages"),
        ])
        logger.info("Bot started successfully!")
    
    # Shutdown event
    async def on_shutdown():
        global heartbeat_task
        logger.info("Bot shutting down...")
        # Stop heartbeat
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        await retention_service.stop()
        await close_clients()
        await bot.session.close()
        logger.info("Bot shut down successfully!")
    
    # Register startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Start polling
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
