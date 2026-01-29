"""
Redis subscriber for ppp:new_posts.

On each new post event: fetch mailing recipients from API and push the post
to each user via RealtimeFeedService.notify_user_new_post.
"""

import asyncio
import json
import logging
import os
import redis.asyncio as redis

from bot.realtime_feed import RealtimeFeedService
from bot.services import get_core_api

logger = logging.getLogger(__name__)

NEW_POSTS_CHANNEL = "ppp:new_posts"
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/1")


async def _run_new_posts_subscriber(feed_service: RealtimeFeedService) -> None:
    """Subscribe to ppp:new_posts and push to recipients."""
    client = redis.from_url(REDIS_URL)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(NEW_POSTS_CHANNEL)
        logger.info("Subscribed to Redis channel %s", NEW_POSTS_CHANNEL)

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Invalid JSON from ppp:new_posts: %s", e)
                continue

            # User-bot sends channel_telegram_id (Telegram channel id) and optionally post_id
            channel_telegram_id = data.get("channel_telegram_id")
            if channel_telegram_id is None:
                logger.warning("Missing channel_telegram_id in new_posts event")
                continue

            api = get_core_api()
            post_id = data.get("post_id")
            if post_id is not None:
                telegram_ids = await api.get_post_recipients(post_id)
            else:
                telegram_ids = await api.get_mailing_recipients_by_telegram_id(channel_telegram_id)
            if not telegram_ids:
                logger.debug("No mailing recipients for channel_telegram_id=%s", channel_telegram_id)
                continue

            post = {
                "id": data.get("post_id"),
                "channel_username": data.get("channel_username", ""),
                "telegram_message_id": data.get("telegram_message_id"),
                "text": data.get("text") or "",
                "media_type": data.get("media_type"),
                "media_file_id": data.get("media_file_id"),
                "posted_at": data.get("posted_at"),
            }

            for user_telegram_id in telegram_ids:
                try:
                    lang = await api.get_user_language(user_telegram_id)
                except Exception:
                    lang = "en_US"
                try:
                    await feed_service.notify_user_new_post(
                        user_id=user_telegram_id,
                        post=post,
                        lang=lang,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to send new post to user %s: %s",
                        user_telegram_id,
                        e,
                        exc_info=True,
                    )

    except asyncio.CancelledError:
        logger.info("New posts subscriber cancelled")
    except Exception as e:
        logger.error("New posts subscriber error: %s", e, exc_info=True)
    finally:
        try:
            await pubsub.unsubscribe(NEW_POSTS_CHANNEL)
            await pubsub.close()
        except Exception:
            pass
        try:
            await client.close()
        except Exception:
            pass


def start_new_posts_subscriber(feed_service: RealtimeFeedService) -> asyncio.Task:
    """Start the Redis new-posts subscriber as a background task."""
    return asyncio.create_task(_run_new_posts_subscriber(feed_service))
