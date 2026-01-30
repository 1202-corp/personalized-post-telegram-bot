"""
Media service for prefetching, caching, and downloading media files.

Handles photo prefetching; for video posts prefetches thumbnail+play overlay as JPEG (main-bot never receives actual video).
"""

import asyncio
import logging
from typing import Optional, Dict, Tuple, List
from bot.types import PostData, UserBotServiceProtocol

logger = logging.getLogger(__name__)


class MediaCache:
    """Thread-safe cache for media files."""
    
    def __init__(self, max_size: int = 30):
        self._cache: Dict[Tuple[int, int], Dict[str, bytes | List[bytes]]] = {}
        self._lock = asyncio.Lock()
        self._max_size = max_size
    
    async def get(
        self,
        chat_id: int,
        post_id: int,
        media_type: str
    ) -> Optional[bytes | List[bytes]]:
        """Get cached media for a post."""
        async with self._lock:
            key = (chat_id, post_id)
            return self._cache.get(key, {}).get(media_type)
    
    async def set(
        self,
        chat_id: int,
        post_id: int,
        media_type: str,
        data: bytes | List[bytes]
    ) -> None:
        """Cache media for a post."""
        async with self._lock:
            key = (chat_id, post_id)
            if key not in self._cache:
                self._cache[key] = {}
            self._cache[key][media_type] = data
            
            # Cleanup old entries if cache is too large
            if len(self._cache) > self._max_size:
                keys = list(self._cache.keys())
                for k in keys[:-self._max_size]:
                    self._cache.pop(k, None)
    
    async def clear(self, chat_id: Optional[int] = None) -> None:
        """Clear cache for a chat or all chats."""
        async with self._lock:
            if chat_id is None:
                self._cache.clear()
            else:
                keys_to_remove = [k for k in self._cache.keys() if k[0] == chat_id]
                for k in keys_to_remove:
                    self._cache.pop(k, None)


class MediaService:
    """Service for managing media prefetching and caching."""
    
    def __init__(self, user_bot: UserBotServiceProtocol):
        self.user_bot = user_bot
        self.cache = MediaCache()
        self._prefetch_tasks: Dict[Tuple[int, int], asyncio.Task] = {}
    
    async def prefetch_post_media(
        self,
        chat_id: int,
        post: PostData
    ) -> None:
        """Prefetch media for a single post."""
        post_id = post.get("id")
        if not post_id:
            return
        
        cache_key = (chat_id, post_id)
        
        # Check if already cached
        if await self.cache.get(chat_id, post_id, "photo") or \
           await self.cache.get(chat_id, post_id, "video"):
            return
        
        # Check if already prefetching
        if cache_key in self._prefetch_tasks:
            return
        
        # Start prefetch task
        task = asyncio.create_task(
            self._prefetch_single_post(chat_id, post)
        )
        self._prefetch_tasks[cache_key] = task
    
    async def _prefetch_single_post(
        self,
        chat_id: int,
        post: PostData
    ) -> None:
        """Internal method to prefetch media for a single post."""
        post_id = post.get("id")
        if not post_id:
            return
        
        cache_key = (chat_id, post_id)
        media_type = post.get("media_type")
        channel_username = post.get("channel_username", "").lstrip("@")
        
        if not channel_username:
            return
        
        try:
            if media_type == "photo":
                media_ids_str = post.get("media_file_id") or ""
                media_ids: List[int] = []
                
                if media_ids_str:
                    for part in media_ids_str.split(","):
                        part = part.strip()
                        if part.isdigit():
                            media_ids.append(int(part))
                
                if media_ids:
                    # Parallel download all photos in album
                    tasks = [
                        self.user_bot.get_photo(channel_username, mid)
                        for mid in media_ids[:5]
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    photos = [
                        r for r in results
                        if r and not isinstance(r, Exception)
                    ]
                    
                    if photos:
                        await self.cache.set(chat_id, post_id, "photo", photos[0])
                        if len(photos) > 1:
                            await self.cache.set(chat_id, post_id, "photos", photos)
            
            elif media_type == "video":
                # get_video returns JPEG (first frame + play overlay), stored under "video" key
                msg_id = post.get("telegram_message_id")
                if msg_id:
                    photo_bytes = await self.user_bot.get_video(channel_username, msg_id)
                    if photo_bytes:
                        await self.cache.set(chat_id, post_id, "video", photo_bytes)
        except Exception as e:
            logger.debug(f"Prefetch failed for post {post_id}: {e}")
        finally:
            # Remove task from tracking
            self._prefetch_tasks.pop(cache_key, None)
    
    async def prefetch_posts_media(
        self,
        chat_id: int,
        posts: List[PostData],
        start_index: int,
        count: int = 5
    ) -> None:
        """Prefetch media for multiple posts in parallel."""
        posts_to_prefetch = posts[start_index:start_index + count]
        
        # Run all prefetches in parallel
        tasks = [
            self.prefetch_post_media(chat_id, post)
            for post in posts_to_prefetch
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def prefetch_all_posts_media(
        self,
        chat_id: int,
        posts: List[PostData]
    ) -> None:
        """Prefetch ALL posts in parallel batches."""
        batch_size = 5
        for i in range(0, len(posts), batch_size):
            batch = posts[i:i + batch_size]
            tasks = [
                self.prefetch_post_media(chat_id, post)
                for post in batch
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            # Small delay between batches to not overwhelm
            await asyncio.sleep(0.1)
    
    async def get_cached_photo(
        self,
        chat_id: int,
        post_id: int
    ) -> Optional[bytes]:
        """Get cached photo bytes for a post."""
        result = await self.cache.get(chat_id, post_id, "photo")
        if isinstance(result, bytes):
            return result
        return None
    
    async def get_cached_photos(
        self,
        chat_id: int,
        post_id: int
    ) -> Optional[List[bytes]]:
        """Get cached photo album bytes for a post."""
        result = await self.cache.get(chat_id, post_id, "photos")
        if isinstance(result, list):
            return result
        return None
    
    async def get_cached_video(
        self,
        chat_id: int,
        post_id: int
    ) -> Optional[bytes]:
        """Get cached photo bytes (JPEG, first frame + play overlay) for a video post."""
        result = await self.cache.get(chat_id, post_id, "video")
        if isinstance(result, bytes):
            return result
        return None
    
    async def clear_cache(self, chat_id: Optional[int] = None) -> None:
        """Clear media cache for a chat or all chats."""
        await self.cache.clear(chat_id)

