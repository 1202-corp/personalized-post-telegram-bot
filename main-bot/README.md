# Personalized Post Bot - Main Bot

> [Русская версия](docs/README-RU.md)

Telegram bot built with Aiogram 3.x implementing AARRR funnel for personalized post recommendations.

## Overview

The main bot handles user interactions, training flows, and personalized feed delivery. It uses a message registry pattern to manage different types of messages (system, ephemeral, onetime).

## Key Features

- User onboarding and training flow
- Personalized post feed based on ML recommendations
- MiniApp integration for swipe interface
- Multi-language support (en_US/ru_RU)
- Message management with registry pattern

## Technology Stack

- **Aiogram 3.x** - Telegram Bot API framework
- **FSM (MemoryStorage)** - User state management
- **httpx** - HTTP client for API communication

## Documentation

- [Russian documentation](docs/README-RU.md)
