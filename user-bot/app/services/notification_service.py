"""
Service for notifying main-bot via Redis about new posts.
"""
import json
import logging
from typing import Optional, List
import redis.asyncio as aioredis

from app.types import PostDataDict, NotificationServiceProtocol

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications via Redis."""
    
    def __init__(self, redis_url: str = "redis://redis:6379/0"):
        """
        Initialize notification service.
        
        Args:
            redis_url: Redis connection URL
        """
        self.redis_url = redis_url
    
    async def notify_new_posts(
        self,
        channel_telegram_id: int,
        channel_username: str,
        channel_title: str,
        posts: List[PostDataDict]
    ) -> bool:
        """
        Notify main-bot about new posts via Redis for real-time delivery.
        
        Args:
            channel_telegram_id: Telegram channel ID
            channel_username: Channel username
            channel_title: Channel title
            posts: List of post data dictionaries
            
        Returns:
            True if successful, False otherwise
        """
        if not posts:
            return True
        
        try:
            redis_client = aioredis.from_url(self.redis_url)
            
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
                await redis_client.publish("ppp:new_posts", json.dumps(event_data))
            
            await redis_client.close()
            logger.info(f"Notified main-bot about {len(posts)} new posts from {channel_username}")
            return True
        except Exception as e:
            logger.error(f"Failed to notify about new posts: {e}")
            return False
    
    async def notify_realtime_post(
        self,
        channel_id: int,
        channel_username: str,
        channel_title: str,
        post_data: PostDataDict,
        post_id: Optional[int] = None
    ) -> None:
        """
        Notify main-bot about new post via Redis.
        
        Args:
            channel_id: Telegram channel ID
            channel_username: Channel username
            channel_title: Channel title
            post_data: Post data dictionary
            post_id: Optional post ID from database
        """
        try:
            redis_client = aioredis.from_url(self.redis_url)
            
            event_data = {
                "channel_telegram_id": channel_id,
                "channel_username": channel_username,
                "channel_title": channel_title,
                "telegram_message_id": post_data["telegram_message_id"],
                "text": post_data.get("text"),
                "media_type": post_data.get("media_type"),
                "media_file_id": post_data.get("media_file_id"),
                "posted_at": post_data["posted_at"],
                "post_id": post_id,
            }
            
            # Publish twice for reliability (as in original code)
            await redis_client.publish("ppp:new_posts", json.dumps(event_data))
            await redis_client.publish("ppp:new_posts", json.dumps(event_data))
            await redis_client.close()
            
            logger.info(f"Real-time: Notified main-bot about post from @{channel_username}")
        except Exception as e:
            logger.error(f"Failed to notify about real-time post: {e}")

