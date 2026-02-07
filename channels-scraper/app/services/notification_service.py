"""
Notify main-bot via Redis about new posts (same contract as user-bot).
"""
import json
import logging
from typing import Optional, Dict, Any

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Publish new-post events to Redis for main-bot."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or get_settings().redis_url

    async def notify_realtime_post(
        self,
        channel_id: int,
        channel_username: str,
        channel_title: str,
        post_data: Dict[str, Any],
        post_id: Optional[int] = None,
    ) -> None:
        """Publish one new post event to ppp:new_posts."""
        try:
            redis_client = aioredis.from_url(self.redis_url)
            event_data = {
                "channel_telegram_id": channel_id,
                "channel_username": channel_username,
                "channel_title": channel_title,
                "telegram_message_id": post_data["telegram_message_id"],
                "text": post_data.get("text"),
                "media_type": post_data.get("media_type"),
                "posted_at": post_data["posted_at"],
                "post_id": post_id,
            }
            await redis_client.publish("ppp:new_posts", json.dumps(event_data))
            await redis_client.close()
            logger.info("Real-time: Notified main-bot about post from @%s", channel_username)
        except Exception as e:
            logger.error("Failed to notify real-time post: %s", e)
