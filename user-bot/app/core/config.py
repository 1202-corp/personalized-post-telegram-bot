"""
Configuration settings for user-bot.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """User bot settings loaded from environment variables."""
    
    # Telegram API credentials (from https://my.telegram.org)
    telegram_api_id: int
    telegram_api_hash: str
    # Session: either file path (e.g. sessions/212349567_telethon.session) or string (TELEGRAM_SESSION_STRING)
    telegram_session_file: str = ""  # If set, use .session file; otherwise use telegram_session_string
    telegram_session_string: str = ""
    
    # Core API URL
    core_api_url: str = "http://api:8000"
    
    # Default training channels (comma-separated)
    default_training_channels: str = ""
    
    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """
    Get settings instance (cached).
    
    Returns:
        Settings instance
    """
    return Settings()
