# Personalized Post Bot - Bot Services

> [Русская версия](docs/README-RU.md)

This directory contains two bot services that work together to provide personalized post recommendations in Telegram.

## Components

### Main Bot (`main-bot/`)

Telegram bot built with Aiogram 3.x implementing AARRR funnel for personalized post recommendations.

**Key Features:**
- User onboarding and training flow
- Personalized post feed based on ML recommendations
- MiniApp integration for swipe interface
- Retention service for inactive users
- Multi-language support (en/ru)
- Message management with registry pattern

**Technology Stack:**
- Aiogram 3.x - Telegram Bot API framework
- FSM (MemoryStorage) - User state management
- httpx - HTTP client for API communication

**Documentation:** [main-bot/README.md](main-bot/README.md)

### User Bot (`user-bot/`)

Telethon-based scraper service with HTTP API for scraping Telegram channels and syncing posts to the main API.

**Key Features:**
- Channel post scraping
- Channel joining
- Media file download (photos, videos)
- Automatic sync to main API
- Health checks

**Technology Stack:**
- Telethon - MTProto client for Telegram
- FastAPI - HTTP API framework
- Session String - Authentication without interactive login

**Documentation:** [user-bot/README.md](user-bot/README.md)

## Architecture

The two bots work together in the following flow:

1. **Main Bot** receives user commands and requests personalized posts
2. **Main Bot** calls the **API** to get recommendations
3. If new posts are needed, **Main Bot** triggers **User Bot** to scrape channels
4. **User Bot** scrapes posts from Telegram channels and syncs them to the **API**
5. **Main Bot** delivers personalized feed to users based on ML recommendations

## Documentation

- [Russian documentation](docs/README-RU.md)

