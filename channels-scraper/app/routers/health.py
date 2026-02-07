"""
Health check endpoints (same contract as user-bot).
"""
import logging
import httpx
from fastapi import APIRouter

from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
async def health_check():
    """Basic health check."""
    return {"status": "healthy", "service": "channels-scraper"}


@router.get("/health/ready")
async def readiness_check():
    """Readiness: Core API and Redis available."""
    checks = {
        "service": "channels-scraper",
        "core_api": "unknown",
        "redis": "unknown",
    }
    all_healthy = True
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.core_api_url.rstrip('/')}/health")
            if response.status_code == 200:
                checks["core_api"] = "healthy"
            else:
                checks["core_api"] = f"unhealthy: status {response.status_code}"
                all_healthy = False
    except Exception as e:
        checks["core_api"] = f"unhealthy: {str(e)[:50]}"
        all_healthy = False
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.close()
        checks["redis"] = "healthy"
    except Exception as e:
        checks["redis"] = f"unhealthy: {str(e)[:50]}"
        all_healthy = False
    checks["status"] = "healthy" if all_healthy else "degraded"
    return checks
