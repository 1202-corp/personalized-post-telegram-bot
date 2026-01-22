#!/usr/bin/env python3
"""
Generate TELEGRAM_SESSION_STRING from Auth Key and DC ID.
"""

import asyncio
from telegram_session_encoder import TelegramSessionEncoder
from telethon import TelegramClient
from telethon.sessions import StringSession

# Твои данные из купленного аккаунта
AUTH_KEY_HEX = "5562b79642e1482024a192cdd236d1015a71885fb0264a91a7d8d29e0e649b91e942ed0936104f8858e16b8e595f2cdd25297392c1f4501b04687a7b3a74ef26116b7e00feec516b281e6b5523670bbb3cc7653ad967390b04bcbbe72921f441e381757bce19bd8e2d3edd594338b5a82f0ed18ea4c23ff9e4f2e9d67306a3f23724c2cea496dd03d15d5253eb1b5eb17d96e6d7b37ee12aa58531e483d7631d24eaa48ee3cff1aa405fd4a88c1a571e9379a47bbca63467b158fffeb8fa07c67863caed383106f070d884d28d07ab43e64dd0f1a4868696e2555d4ed96cf731b5b77785e16377d71f9cd20006599990410fbe694ecce1e9dd2728e6c84e7b63"  # Замени на свой полный ключ
DC_ID = 4
USER_ID = 8132411990

# Публичные API credentials (работают везде)
API_ID = 94575
API_HASH = "a3406de8a5e3c6e52d1df6f81aa4c826"


def generate_session_string():
    """Генерирует StringSession из Auth Key и DC ID."""
    auth_key = bytes.fromhex(AUTH_KEY_HEX)
    session_encoder = TelegramSessionEncoder(auth_key, DC_ID)
    session_string = session_encoder.to_string()
    return session_string


async def verify_session(session_string):
    """Проверяет, что сессия валидная."""
    try:
        string_session = StringSession(session_string)
        async with TelegramClient(
            session=string_session,
            api_id=API_ID,
            api_hash=API_HASH
        ) as client:
            me = await client.get_me()
            print(f"✓ Успешно! Залогинен как: {me.first_name} {me.last_name or ''}")
            return True
    except Exception as e:
        print(f"✗ Ошибка сессии: {e}")
        return False


async def main():
    print("=" * 60)
    print("Telegram Session String Generator")
    print("=" * 60)
    print()
    
    # Генерируем StringSession
    session_string = generate_session_string()
    
    print("Сгенерирована строка сессии:")
    print()
    print(session_string)
    print()
    
    # Проверяем валидность
    print("Проверка валидности сессии...")
    is_valid = await verify_session(session_string)
    
    if is_valid:
        print(f"  TELEGRAM_API_ID={API_ID}")
        print(f"  TELEGRAM_API_HASH={API_HASH}")
        print(f"  TELEGRAM_SESSION_STRING=...{session_string[-20:]}")
    else:
        print()
        print("⚠️  Сессия невалидная. Проверь Auth Key и DC ID.")


if __name__ == "__main__":
    asyncio.run(main())
