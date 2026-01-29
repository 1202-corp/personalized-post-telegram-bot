"""
HTTP client for communicating with api and user-bot services.

This module provides a unified interface to all API services.
"""

import logging
import json
import base64
from typing import Optional, Dict, Any, List
import httpx
import redis.asyncio as aioredis
from bot.core.config import get_settings

from bot.services.api.users import UserService
from bot.services.api.channels import ChannelService
from bot.services.api.posts import PostService
from bot.services.api.ml import MLService

logger = logging.getLogger(__name__)
settings = get_settings()

# TTL for post content cache: 6 hours
CACHE_TTL_SECONDS = 6 * 60 * 60  # 21600 seconds


class CoreAPIClient:
    """Unified client for api service with all domain services."""
    
    def __init__(self):
        self.users = UserService()
        self.channels = ChannelService()
        self.posts = PostService()
        self.ml = MLService()
    
    async def close(self):
        """Close all service clients."""
        await self.users.close()
        await self.channels.close()
        await self.posts.close()
        await self.ml.close()
    
    # Delegate methods for backward compatibility
    async def get_or_create_user(self, *args, **kwargs):
        """Get or create user with language support."""
        return await self.users.get_or_create_user(*args, **kwargs)
    
    async def get_user(self, *args, **kwargs):
        return await self.users.get_user(*args, **kwargs)
    
    async def update_user(self, *args, **kwargs):
        return await self.users.update_user(*args, **kwargs)
    
    async def update_activity(self, *args, **kwargs):
        return await self.users.update_activity(*args, **kwargs)
    
    async def create_log(self, *args, **kwargs):
        return await self.users.create_log(*args, **kwargs)
    
    async def get_user_language(self, *args, **kwargs):
        return await self.users.get_user_language(*args, **kwargs)
    
    async def set_user_language(self, *args, **kwargs):
        return await self.users.set_user_language(*args, **kwargs)
    
    async def get_feed_users(self, *args, **kwargs):
        return await self.users.get_feed_users(*args, **kwargs)
    
    async def get_default_channels(self, *args, **kwargs):
        return await self.channels.get_default_channels(*args, **kwargs)
    
    async def add_user_channel(self, *args, **kwargs):
        return await self.channels.add_user_channel(*args, **kwargs)
    
    async def get_user_channels(self, *args, **kwargs):
        return await self.channels.get_user_channels(*args, **kwargs)
    
    async def get_user_interactions(self, *args, **kwargs):
        return await self.posts.get_user_interactions(*args, **kwargs)
    
    async def get_training_posts(self, *args, **kwargs):
        return await self.posts.get_training_posts(*args, **kwargs)
    
    async def create_interaction(self, *args, **kwargs):
        return await self.posts.create_interaction(*args, **kwargs)
    
    async def get_best_posts(self, *args, **kwargs):
        return await self.posts.get_best_posts(*args, **kwargs)
    
    async def train_model(self, *args, **kwargs):
        return await self.ml.train_model(*args, **kwargs)
    
    async def check_training_eligibility(self, *args, **kwargs):
        return await self.ml.check_training_eligibility(*args, **kwargs)
    
    async def get_recommendations(self, *args, **kwargs):
        return await self.ml.get_recommendations(*args, **kwargs)
    
    async def get_post(self, *args, **kwargs):
        return await self.posts.get_post(*args, **kwargs)
    
    async def get_users_by_channel(self, channel_username: str):
        """Get users subscribed to a channel (via user channels)."""
        return await self.channels.get_users_by_channel(channel_username)


class UserBotClient:
    """Client for user-bot service (scraper)."""
    
    def __init__(self):
        self.base_url = settings.user_bot_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=60.0)
    
    async def close(self):
        await self.client.aclose()
    
    async def scrape_channel(
        self,
        channel_username: str,
        limit: int = 7,
        for_training: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Trigger channel scraping.
        
        Args:
            channel_username: Channel username
            limit: Number of posts to scrape
            for_training: If True, don't store text in DB (only metadata) - text will be fetched on-demand
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/cmd/scrape",
                json={
                    "channel_username": channel_username,
                    "limit": limit,
                    "for_training": for_training,
                }
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error scraping channel {channel_username}: {e}")
            return None
    
    async def join_channel(self, channel_username: str) -> Optional[Dict[str, Any]]:
        """Request user-bot to join a channel."""
        try:
            response = await self.client.post(
                f"{self.base_url}/cmd/join",
                json={"channel_username": channel_username}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error joining channel {channel_username}: {e}")
            return None
    
    async def _get_media(
        self,
        media_type: str,
        channel_username: str,
        message_id: int,
        timeout: Optional[float] = None,
        return_json: bool = False
    ) -> Optional[Any]:
        """
        Helper method to fetch media from user-bot.
        
        Args:
            media_type: Type of media ('photo', 'video', 'text')
            channel_username: Channel username
            message_id: Telegram message ID
            timeout: Optional timeout override
            return_json: If True, parse response as JSON and return 'text' field
            
        Returns:
            bytes for photo/video, str for text, or None on error
        """
        try:
            kwargs = {
                "params": {
                    "channel_username": channel_username,
                    "message_id": message_id,
                }
            }
            if timeout:
                kwargs["timeout"] = timeout
            
            response = await self.client.get(
                f"{self.base_url}/media/{media_type}",
                **kwargs
            )
            if response.status_code == 200:
                if return_json:
                    data = response.json()
                    return data.get("text")
                return response.content
            return None
        except Exception as e:
            logger.error(f"Error fetching {media_type} for {channel_username}#{message_id}: {e}")
            return None
    
    async def get_photo(self, channel_username: str, message_id: int) -> Optional[bytes]:
        """Fetch photo bytes for a specific channel message from user-bot."""
        return await self._get_media("photo", channel_username, message_id)
    
    async def get_video(self, channel_username: str, message_id: int) -> Optional[bytes]:
        """Fetch video bytes for a specific channel message from user-bot."""
        return await self._get_media("video", channel_username, message_id, timeout=30.0)
    
    async def get_post_text(self, channel_username: str, message_id: int) -> Optional[str]:
        """Fetch post text in HTML format for a specific channel message from user-bot."""
        return await self._get_media("text", channel_username, message_id, return_json=True)
    
    async def get_post_full_content(
        self,
        channel_username: str,
        message_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch full post content (text and media) from user-bot.
        
        Args:
            channel_username: Channel username
            message_id: Telegram message ID
            
        Returns:
            Dict with text, media_type, media_data (base64) or None
        """
        try:
            response = await self.client.get(
                f"{self.base_url}/media/full",
                params={
                    "channel_username": channel_username,
                    "message_id": message_id,
                },
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error fetching full post content for {channel_username}#{message_id}: {e}")
            return None
    
    async def get_media_group_photos(
        self, channel_username: str, message_ids: List[int]
    ) -> List[bytes]:
        """Fetch photos for a media group (multiple messages)."""
        photos = []
        for msg_id in message_ids:
            photo = await self.get_photo(channel_username, msg_id)
            if photo:
                photos.append(photo)
        return photos
    
    async def health_check(self) -> bool:
        """Check if user-bot is healthy."""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False


class PostCacheClient:
    """Client for caching post content in Redis."""
    
    def __init__(self):
        self.redis_url = settings.redis_url
        self._redis_client: Optional[aioredis.Redis] = None
    
    async def _get_redis_client(self) -> aioredis.Redis:
        """Get or create Redis client."""
        if self._redis_client is None:
            self._redis_client = aioredis.from_url(
                self.redis_url,
                decode_responses=False,  # We store binary data
                socket_connect_timeout=5,
                socket_timeout=5,
            )
        return self._redis_client
    
    async def close(self):
        """Close Redis connection."""
        if self._redis_client:
            await self._redis_client.aclose()
            self._redis_client = None
    
    def _get_cache_key(self, post_id: int) -> str:
        """Get Redis key for post content cache."""
        return f"post:{post_id}:content"
    
    async def get_post_content(self, post_id: int) -> Optional[Dict[str, Any]]:
        """
        Get post content (text and media) from Redis cache.
        
        Args:
            post_id: Post ID
            
        Returns:
            Dict with keys: text, media_type, media_data, cached_at
            or None if not found/expired
        """
        try:
            redis_client = await self._get_redis_client()
            cache_key = self._get_cache_key(post_id)
            
            # Get hash data
            data = await redis_client.hgetall(cache_key)
            if not data:
                return None
            
            # Decode hash fields
            result = {}
            for key, value in data.items():
                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                if key_str == 'media_data' and value:
                    # media_data is base64 encoded
                    result[key_str] = base64.b64decode(value).decode('utf-8') if value else None
                elif key_str == 'cached_at':
                    result[key_str] = value.decode('utf-8') if isinstance(value, bytes) else value
                else:
                    result[key_str] = value.decode('utf-8') if isinstance(value, bytes) else value
            
            return result if result else None
        except Exception as e:
            logger.error(f"Error getting post content from cache (post_id={post_id}): {e}")
            return None
    
    async def set_post_content(
        self,
        post_id: int,
        text: Optional[str] = None,
        media_type: Optional[str] = None,
        media_data: Optional[str] = None  # base64 encoded string
    ) -> bool:
        """
        Cache post content (text and media) in Redis.
        
        Args:
            post_id: Post ID
            text: HTML text content
            media_type: Type of media (photo, video, etc.)
            media_data: Media data as base64 encoded string
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from datetime import datetime
            redis_client = await self._get_redis_client()
            cache_key = self._get_cache_key(post_id)
            
            # Prepare hash data
            cache_data = {
                'cached_at': datetime.utcnow().isoformat().encode('utf-8'),
            }
            
            if text is not None:
                cache_data['text'] = text.encode('utf-8')
            
            if media_type is not None:
                cache_data['media_type'] = media_type.encode('utf-8')
            
            if media_data is not None:
                # media_data is already base64 encoded string
                cache_data['media_data'] = media_data.encode('utf-8')
            
            # Store as hash with TTL
            await redis_client.hset(cache_key, mapping=cache_data)
            await redis_client.expire(cache_key, CACHE_TTL_SECONDS)
            
            logger.debug(f"Cached post content (post_id={post_id}, has_text={text is not None}, has_media={media_data is not None})")
            return True
        except Exception as e:
            logger.error(f"Error caching post content (post_id={post_id}): {e}")
            return False
    
    async def invalidate_post_cache(self, post_id: int) -> bool:
        """
        Remove post content from cache.
        
        Args:
            post_id: Post ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            redis_client = await self._get_redis_client()
            cache_key = self._get_cache_key(post_id)
            result = await redis_client.delete(cache_key)
            logger.debug(f"Invalidated post cache (post_id={post_id}, deleted={result > 0})")
            return result > 0
        except Exception as e:
            logger.error(f"Error invalidating post cache (post_id={post_id}): {e}")
            return False


# Singleton instances
_core_api_client: Optional[CoreAPIClient] = None
_user_bot_client: Optional[UserBotClient] = None
_post_cache_client: Optional[PostCacheClient] = None


def get_core_api() -> CoreAPIClient:
    global _core_api_client
    if _core_api_client is None:
        _core_api_client = CoreAPIClient()
    return _core_api_client


def get_user_bot() -> UserBotClient:
    global _user_bot_client
    if _user_bot_client is None:
        _user_bot_client = UserBotClient()
    return _user_bot_client


def get_post_cache() -> PostCacheClient:
    """Get singleton PostCacheClient instance."""
    global _post_cache_client
    if _post_cache_client is None:
        _post_cache_client = PostCacheClient()
    return _post_cache_client


async def close_clients():
    global _core_api_client, _user_bot_client, _post_cache_client
    if _core_api_client:
        await _core_api_client.close()
    if _user_bot_client:
        await _user_bot_client.close()
    if _post_cache_client:
        await _post_cache_client.close()
