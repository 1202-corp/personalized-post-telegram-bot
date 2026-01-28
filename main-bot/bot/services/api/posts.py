"""Post service for API interactions."""

import logging
from typing import List, Dict, Any
from .base import BaseAPIClient

logger = logging.getLogger(__name__)


class PostService(BaseAPIClient):
    """Service for post-related API endpoints."""
    
    async def get_training_posts(
        self,
        telegram_id: int,
        channel_usernames: List[str],
        posts_per_channel: int = 7
    ) -> List[Dict[str, Any]]:
        """Get posts for training."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/posts/training",
                json={
                    "user_telegram_id": telegram_id,
                    "channel_usernames": channel_usernames,
                    "posts_per_channel": posts_per_channel,
                }
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting training posts: {e}")
            return []
    
    async def create_interaction(
        self,
        telegram_id: int,
        post_id: int,
        interaction_type: str
    ) -> bool:
        """Create a user interaction with a post."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/posts/interactions",
                json={
                    "user_telegram_id": telegram_id,
                    "post_id": post_id,
                    "interaction_type": interaction_type,
                }
            )
            return response.status_code == 201
        except Exception as e:
            logger.error(f"Error creating interaction: {e}")
            return False
    
    async def get_best_posts(
        self,
        telegram_id: int,
        limit: int = 1
    ) -> List[Dict[str, Any]]:
        """Get best posts for user feed."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/posts/best",
                json={
                    "user_telegram_id": telegram_id,
                    "limit": limit,
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("posts", [])
        except Exception as e:
            logger.error(f"Error getting best posts: {e}")
            return []
    
    async def get_user_interactions(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Get all interactions for a user."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/posts/interactions/{telegram_id}"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting user interactions: {e}")
            return []
    
    async def get_post(self, post_id: int) -> Dict[str, Any] | None:
        """Get post by ID."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/posts/{post_id}"
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting post {post_id}: {e}")
            return None

