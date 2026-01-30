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

from bot.core import get_settings, setup_logging, get_logger, MessageManager
from bot.core.middleware import MessageManagerMiddleware, AutoDeleteUserMessagesMiddleware
from bot.services import close_clients
from bot.handlers import commands
from bot.handlers.training import router as training_router
from bot.handlers.feed import router as feed_router
from bot.redis_subscriber import RedisSubscriber
from bot.realtime_feed import RealtimeFeedService
from bot.new_posts_subscriber import start_new_posts_subscriber

# Configure logging
setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    log_dir=os.getenv("LOG_DIR", "/var/log/ppp"),
    log_file="main-bot.log",
)
logger = get_logger(__name__)

settings = get_settings()

# Redis heartbeat and subscriber
redis_client = None
heartbeat_task = None
redis_subscriber: RedisSubscriber | None = None
new_posts_task = None

async def heartbeat_loop():
    """Send heartbeat to Redis every 30 seconds."""
    global redis_client
    try:
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/1"))
        while True:
            try:
                await redis_client.set("ppp:main_bot:heartbeat", "alive", ex=60)
                await redis_client.set("ppp:main_bot:last_seen", str(int(asyncio.get_event_loop().time())), ex=120)
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
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Initialize dispatcher with memory storage
    # In production, use Redis storage for persistence
    dp = Dispatcher(storage=MemoryStorage())
    
    # Initialize message manager
    message_manager = MessageManager(bot)
    
    # Register routers
    dp.include_router(commands.router)
    dp.include_router(training_router)
    dp.include_router(feed_router)
    
    # Middleware to inject message_manager into handlers
    dp.update.middleware(MessageManagerMiddleware(message_manager))
    # Middleware to automatically delete all user messages (registered on update level to catch all messages)
    dp.update.middleware(AutoDeleteUserMessagesMiddleware(message_manager))
    
    # Handler for training_complete from MiniApp
    async def handle_training_complete(data: dict):
        """Handle training_complete notification from API via Redis."""
        telegram_id = data.get("telegram_id")
        chat_id = data.get("chat_id", telegram_id)
        rated_count = data.get("rated_count", 0)
        
        if not telegram_id:
            logger.warning("training_complete without telegram_id")
            return
        
        logger.info(f"Received training_complete for user {telegram_id}, rated_count={rated_count}")
        
        try:
            from bot.handlers.training.helpers import _get_user_lang
            from bot.handlers.training.flow import finish_training_flow
            from aiogram.fsm.context import FSMContext
            from aiogram.fsm.storage.base import StorageKey
            
            # Get FSM context for user
            key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=telegram_id)
            state = FSMContext(storage=dp.storage, key=key)
            
            # Set state data for finish_training_flow
            await state.update_data(
                user_id=telegram_id,
                rated_count=rated_count,
                is_bonus_training=False,
                is_retrain=False,
            )
            
            await finish_training_flow(chat_id, message_manager, state)
        except Exception as e:
            logger.error(f"Error handling training_complete for {telegram_id}: {e}", exc_info=True)
    
    # Handler for new posts from user-bot
    async def handle_new_post(data: dict):
        """Handle new post notification from user-bot via Redis."""
        channel_username = data.get("channel_username", "")
        channel_title = data.get("channel_title", "")
        post_id = data.get("post_id")
        # Get text and media directly from event (user-bot sends full data)
        event_text = data.get("text")
        event_media_type = data.get("media_type")
        event_media_file_id = data.get("media_file_id")
        telegram_message_id = data.get("telegram_message_id")
        
        logger.info(f"Received new_post from @{channel_username}, post_id={post_id}, has_text={bool(event_text)}")
        
        if not post_id:
            logger.debug("new_post without post_id, skipping real-time delivery")
            return
        
        try:
            from bot.services import get_core_api
            from bot.realtime_feed import RealtimeFeedService
            
            api = get_core_api()
            
            # Get users subscribed to this channel who are trained
            users = await api.get_users_by_channel(channel_username.lstrip("@"))
            
            if not users:
                logger.debug(f"No users subscribed to @{channel_username}")
                return
            
            # Build post dict from event data (user-bot sends everything we need)
            post = {
                "id": post_id,
                "telegram_message_id": telegram_message_id,
                "text": event_text,
                "media_type": event_media_type,
                "media_file_id": event_media_file_id,
                "channel_username": channel_username,
                "channel_title": channel_title,
            }
            
            # Initialize realtime feed service
            feed_service = RealtimeFeedService(bot, message_manager)
            
            # Send to each subscribed and trained user
            for user in users:
                if user.get("is_trained"):
                    telegram_id = user.get("telegram_id")
                    lang = user.get("language", "en_US")
                    await feed_service.notify_user_new_post(telegram_id, post, lang)
                    
        except Exception as e:
            logger.error(f"Error handling new_post: {e}", exc_info=True)
    
    # Startup event
    async def on_startup():
        global heartbeat_task, redis_subscriber, new_posts_task
        logger.info("Bot starting up...")
        # Start heartbeat
        heartbeat_task = asyncio.create_task(heartbeat_loop())
        # Redis subscriber for training_complete (MiniApp flow)
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/1")
        redis_subscriber = RedisSubscriber(redis_url)
        redis_subscriber.register_handler("ppp:training_complete", handle_training_complete)
        await redis_subscriber.start()
        # New-posts subscriber (taste-filtered delivery)
        feed_service = RealtimeFeedService(bot, message_manager)
        new_posts_task = start_new_posts_subscriber(feed_service)
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
        global heartbeat_task, redis_subscriber, new_posts_task
        logger.info("Bot shutting down...")
        if redis_subscriber:
            await redis_subscriber.stop()
        if new_posts_task:
            new_posts_task.cancel()
            try:
                await new_posts_task
            except asyncio.CancelledError:
                pass
        # Stop heartbeat
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
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
