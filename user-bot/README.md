# Personalized Post Bot - User Bot

> [Русская версия](docs/README-RU.md)

Telethon-based scraper service with HTTP API for scraping Telegram channels and syncing posts to the main API.

## Overview

The user bot provides HTTP endpoints for scraping channel posts, joining channels, and downloading media files. It uses Telethon for MTProto communication with Telegram servers.

## Key Features

- Channel post scraping
- Channel joining
- Media file download (photos, videos)
- Automatic sync to main API
- Health checks

## Technology Stack

- **Telethon** - MTProto client for Telegram
- **FastAPI** - HTTP API framework
- **Session String** - Authentication without interactive login

## API Endpoints

- `POST /cmd/scrape` - Scrape channel posts
- `POST /cmd/join` - Join a channel
- `GET /media/photo` - Download photo
- `GET /media/video` - Download video
- `GET /health` - Health check
- `GET /health/ready` - Readiness check

## Documentation

- [Russian documentation](docs/README-RU.md)
