from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """User bot settings."""
    
    # Telegram API credentials (from https://my.telegram.org)
    telegram_api_id: int
    telegram_api_hash: str
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
    return Settings()
