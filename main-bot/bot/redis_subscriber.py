"""
Redis pub/sub subscriber for receiving notifications from API.

Handles:
- training_complete: When user finishes training in MiniApp
- new_post: When a new post is detected in a subscribed channel
"""

import asyncio
import json
import logging
from typing import Callable, Awaitable, Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisSubscriber:
    """Subscribe to Redis pub/sub channels and dispatch messages to handlers."""
    
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._handlers: dict[str, Callable[[dict], Awaitable[None]]] = {}
    
    def register_handler(self, channel: str, handler: Callable[[dict], Awaitable[None]]):
        """Register a handler for a specific channel."""
        self._handlers[channel] = handler
        logger.info(f"Registered handler for channel: {channel}")
    
    async def start(self):
        """Start the subscriber."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._subscribe_loop())
        logger.info("Redis subscriber started")
    
    async def stop(self):
        """Stop the subscriber."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        
        logger.info("Redis subscriber stopped")
    
    async def _subscribe_loop(self):
        """Main subscription loop with reconnection logic."""
        while self._running:
            try:
                await self._connect_and_subscribe()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Redis subscriber error: {e}")
                await asyncio.sleep(5)  # Wait before reconnecting
    
    async def _connect_and_subscribe(self):
        """Connect to Redis and subscribe to channels."""
        self._redis = aioredis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        
        self._pubsub = self._redis.pubsub()
        
        # Subscribe to all registered channels
        channels = list(self._handlers.keys())
        if channels:
            await self._pubsub.subscribe(*channels)
            logger.info(f"Subscribed to channels: {channels}")
        
        # Listen for messages
        async for message in self._pubsub.listen():
            if not self._running:
                break
            
            if message["type"] == "message":
                channel = message["channel"]
                data = message["data"]
                
                try:
                    parsed_data = json.loads(data) if isinstance(data, str) else data
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from channel {channel}: {data}")
                    continue
                
                handler = self._handlers.get(channel)
                if handler:
                    try:
                        await handler(parsed_data)
                    except Exception as e:
                        logger.error(f"Handler error for channel {channel}: {e}", exc_info=True)
