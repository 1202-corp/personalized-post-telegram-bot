"""Base API client with common functionality."""

import logging
import httpx
from bot.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class BaseAPIClient:
    """Base client for API service with common HTTP client."""
    
    def __init__(self):
        self.base_url = settings.core_api_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

