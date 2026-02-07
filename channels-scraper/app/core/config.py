"""
Configuration for channels-scraper (no Telegram account).
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Channels-scraper settings from environment."""

    # Core API URL (channels and posts)
    core_api_url: str = "http://api:8000"

    # Redis for real-time notifications to main-bot
    redis_url: str = "redis://redis:6379/0"

    # Poll interval in seconds: check all channels for new posts
    poll_interval_sec: int = 90

    # Max concurrent requests when fetching multiple posts (reduces total time)
    scraper_concurrent: int = 10

    # Request timeout for t.me
    scraper_timeout_sec: int = 15

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()
