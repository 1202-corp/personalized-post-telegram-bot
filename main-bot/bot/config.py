from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Bot settings loaded from environment variables."""
    
    # Telegram Bot
    telegram_bot_token: str
    
    # Service URLs
    core_api_url: str = "http://api:8000"
    user_bot_url: str = "http://user-bot:8001"
    miniapp_url: str = "http://localhost:8080"
    
    # Redis for state storage
    redis_url: str = "redis://redis:6379/1"
    
    # Training settings
    default_training_channels: str = "@durov,@telegram"
    posts_per_channel: int = 7
    min_interactions_for_training: int = 5
    
    # Localization (using locale format: language_COUNTRY)
    default_language: str = "en_US"
    
    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
