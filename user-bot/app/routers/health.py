"""
Health check endpoints.
"""
import logging
import httpx
from fastapi import APIRouter

from app.core.config import get_settings
from app.services import get_telethon_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "user-bot"}


@router.get("/health/ready")
async def readiness_check():
    """
    Readiness check - verifies Telethon and core-api are available.
    
    Returns:
        Dictionary with health status of all dependencies
    """
    telethon_service = get_telethon_service()
    checks = {
        "service": "user-bot",
        "telethon": "unknown",
        "core_api": "unknown",
    }
    all_healthy = True
    
    # Check Telethon
    if telethon_service.is_connected:
        checks["telethon"] = "healthy"
    else:
        checks["telethon"] = "unhealthy: not connected"
        all_healthy = False
    
    # Check core-api
    try:
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            response = await http_client.get(f"{settings.core_api_url}/health")
            if response.status_code == 200:
                checks["core_api"] = "healthy"
            else:
                checks["core_api"] = f"unhealthy: status {response.status_code}"
                all_healthy = False
    except Exception as e:
        checks["core_api"] = f"unhealthy: {str(e)[:50]}"
        all_healthy = False
    
    checks["status"] = "healthy" if all_healthy else "degraded"
    return checks

