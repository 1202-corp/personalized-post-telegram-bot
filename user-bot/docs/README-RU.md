# User Bot

> [English version](../README.md)

Telethon-based скрейпер каналов с HTTP API для скрейпинга постов и синхронизации с основным API.

## Описание

User Bot предоставляет HTTP эндпоинты для скрейпинга постов из каналов, присоединения к каналам и скачивания медиа файлов. Использует Telethon для MTProto коммуникации с серверами Telegram.

## Основные функции

- Скрейпинг постов из каналов
- Присоединение к каналам
- Скачивание медиа файлов (фото, видео)
- Автоматическая синхронизация с основным API
- Health checks

## Технологии

- **Telethon** — MTProto клиент для Telegram
- **FastAPI** — HTTP API фреймворк
- **Session String** — Авторизация без интерактивного входа

## API Endpoints

- `POST /cmd/scrape` - Скрейпинг постов канала
- `POST /cmd/join` - Присоединиться к каналу
- `GET /media/photo` - Скачать фото
- `GET /media/video` - Скачать видео
- `GET /health` - Health check
- `GET /health/ready` - Readiness check

## Структура

```
app/
├── main.py            # FastAPI приложение
├── config.py          # Настройки
└── telethon_client.py # Telethon клиент
```

## Генерация Session String

Используйте скрипт `scripts/generate_session.py` для генерации session string, который затем нужно добавить в переменную окружения `TELEGRAM_SESSION_STRING`.

