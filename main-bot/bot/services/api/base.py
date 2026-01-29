"""Base API client with common functionality."""

import logging
from typing import Optional, Callable, Awaitable, TypeVar
import httpx
from bot.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

T = TypeVar('T')


class BaseAPIClient:
    """Base client for API service with common HTTP client."""
    
    def __init__(self):
        self.base_url = settings.core_api_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
    
    async def _handle_request(
        self,
        operation_name: str,
        request_func: Callable[[], Awaitable[httpx.Response]],
        default_return: T,
        log_error: bool = True
    ) -> T:
        """
        Helper method to handle API requests with consistent error handling.
        
        Args:
            operation_name: Name of the operation for logging
            request_func: Async function that makes the HTTP request
            default_return: Default value to return on error
            log_error: Whether to log errors (default: True)
            
        Returns:
            Result from request_func or default_return on error
        """
        try:
            response = await request_func()
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return default_return
            if log_error:
                logger.error(f"Error {operation_name}: HTTP {e.response.status_code}")
            return default_return
        except Exception as e:
            if log_error:
                logger.error(f"Error {operation_name}: {e}")
            return default_return

