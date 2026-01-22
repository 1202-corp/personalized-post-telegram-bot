"""ML service for API interactions."""

import logging
from typing import Optional, List, Dict, Any
from .base import BaseAPIClient

logger = logging.getLogger(__name__)


class MLService(BaseAPIClient):
    """Service for ML-related API endpoints."""
    
    async def train_model(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Trigger model training for user."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/ml/train",
                json={"user_telegram_id": telegram_id},
                timeout=60.0  # Training can take a while
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error training model: {e}")
            return None
    
    async def check_training_eligibility(
        self,
        telegram_id: int
    ) -> tuple[bool, str]:
        """Check if user is eligible for training."""
        try:
            response = await self.client.get(
                f"{self.base_url}/api/v1/ml/eligibility/{telegram_id}"
            )
            response.raise_for_status()
            data = response.json()
            return data.get("eligible", False), data.get("message", "")
        except Exception as e:
            logger.error(f"Error checking eligibility: {e}")
            return False, str(e)
    
    async def get_recommendations(
        self,
        telegram_id: int,
        limit: int = 10,
        exclude_interacted: bool = True
    ) -> List[Dict[str, Any]]:
        """Get personalized post recommendations for a user."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/ml/recommendations",
                json={
                    "user_telegram_id": telegram_id,
                    "limit": limit,
                    "exclude_interacted": exclude_interacted,
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("recommendations", [])
        except Exception as e:
            logger.error(f"Error getting recommendations: {e}")
            return []

