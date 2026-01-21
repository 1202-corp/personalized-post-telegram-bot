#!/usr/bin/env python3
"""
Generate Telethon session string for user-bot.

This script helps you create a session string that allows the user-bot
to authenticate with Telegram without requiring interactive login.

Usage:
    # Interactive mode (prompts for credentials)
    python scripts/generate_session.py

    # Command line arguments mode
    python scripts/generate_session.py --api-id 12345 --api-hash abcdef123456

    # Using environment variables
    export TELEGRAM_API_ID=12345
    export TELEGRAM_API_HASH=abcdef123456
    python scripts/generate_session.py

    # Save directly to .env file
    python scripts/generate_session.py --api-id 12345 --api-hash abcdef123456 --save-env

Requirements:
    pip install telethon

Get credentials from: https://my.telegram.org
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    print("Error: telethon is not installed.", file=sys.stderr)
    print("Install it with: pip install telethon", file=sys.stderr)
    sys.exit(1)


def get_credentials_interactive() -> tuple[int, str]:
    """Get API credentials via interactive prompts."""
    print("=" * 60)
    print("Telethon Session String Generator")
    print("=" * 60)
    print()
    print("You need API ID and API Hash from https://my.telegram.org")
    print("1. Go to https://my.telegram.org")
    print("2. Log in with your phone number")
    print("3. Go to 'API development tools'")
    print("4. Create an application to get your credentials")
    print()
    
    while True:
        api_id_str = input("Enter your API ID: ").strip()
        if not api_id_str:
            print("Error: API ID cannot be empty")
            continue
        
        try:
            api_id = int(api_id_str)
            break
        except ValueError:
            print("Error: API ID must be a number")
    
    while True:
        api_hash = input("Enter your API Hash: ").strip()
        if not api_hash:
            print("Error: API Hash cannot be empty")
            continue
        break
    
    return api_id, api_hash


def get_credentials_from_env() -> Optional[tuple[int, str]]:
    """Get API credentials from environment variables."""
    api_id_str = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    
    if not api_id_str or not api_hash:
        return None
    
    try:
        api_id = int(api_id_str)
        return api_id, api_hash
    except ValueError:
        print("Error: TELEGRAM_API_ID must be a number", file=sys.stderr)
        return None


def save_to_env_file(session_string: str, env_file: Path = Path(".env")) -> bool:
    """Save session string to .env file."""
    try:
        # Read existing .env if it exists
        existing_content = ""
        if env_file.exists():
            existing_content = env_file.read_text(encoding="utf-8")
        
        # Check if TELEGRAM_SESSION_STRING already exists
        if "TELEGRAM_SESSION_STRING=" in existing_content:
            # Update existing line
            lines = existing_content.splitlines()
            updated = False
            for i, line in enumerate(lines):
                if line.startswith("TELEGRAM_SESSION_STRING="):
                    lines[i] = f"TELEGRAM_SESSION_STRING={session_string}"
                    updated = True
                    break
            
            if updated:
                env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
                print(f"✓ Updated TELEGRAM_SESSION_STRING in {env_file}")
            else:
                return False
        else:
            # Append new line
            with env_file.open("a", encoding="utf-8") as f:
                if existing_content and not existing_content.endswith("\n"):
                    f.write("\n")
                f.write(f"TELEGRAM_SESSION_STRING={session_string}\n")
            print(f"✓ Added TELEGRAM_SESSION_STRING to {env_file}")
        
        return True
    except Exception as e:
        print(f"Error saving to .env file: {e}", file=sys.stderr)
        return False


async def generate_session(
    api_id: int,
    api_hash: str,
    save_env: bool = False,
    env_file: Optional[Path] = None
) -> str:
    """Generate and return session string."""
    print()
    print("Connecting to Telegram...")
    print("You will receive a verification code via Telegram or SMS.")
    print()
    
    try:
        async with TelegramClient(StringSession(), api_id, api_hash) as client:
            # This will prompt for phone, code, etc.
            await client.connect()
            
            if not await client.is_user_authorized():
                print("\nPlease authorize:")
                await client.send_code_request(client.phone or "")
                code = input("Enter the code you received: ").strip()
                await client.sign_in(code=code)
            
            session_string = client.session.save()
            
            print()
            print("=" * 60)
            print("SUCCESS! Your session string is:")
            print("=" * 60)
            print()
            print(session_string)
            print()
            print("=" * 60)
            print()
            
            if save_env:
                target_file = env_file or Path(".env")
                if save_to_env_file(session_string, target_file):
                    print()
                    print(f"Session string saved to {target_file}")
                else:
                    print()
                    print("Warning: Could not save to .env file automatically.")
                    print("Please add it manually:")
                    print(f"TELEGRAM_SESSION_STRING={session_string}")
            else:
                print("Add this to your .env file as:")
                print(f"TELEGRAM_SESSION_STRING={session_string}")
            
            print()
            print("⚠️  SECURITY WARNING:")
            print("   Keep this string secret!")
            print("   Anyone with this string can access your Telegram account.")
            print("   Never commit it to version control (git).")
            print()
            
            return session_string
    
    except Exception as e:
        print(f"\nError generating session: {e}", file=sys.stderr)
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate Telethon session string for user-bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  %(prog)s

  # With command line arguments
  %(prog)s --api-id 12345 --api-hash abcdef123456

  # Save directly to .env
  %(prog)s --api-id 12345 --api-hash abcdef123456 --save-env

  # Specify custom .env file
  %(prog)s --api-id 12345 --api-hash abcdef123456 --save-env --env-file .env.local
        """
    )
    
    parser.add_argument(
        "--api-id",
        type=int,
        help="Telegram API ID (from https://my.telegram.org)"
    )
    
    parser.add_argument(
        "--api-hash",
        type=str,
        help="Telegram API Hash (from https://my.telegram.org)"
    )
    
    parser.add_argument(
        "--save-env",
        action="store_true",
        help="Automatically save session string to .env file"
    )
    
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to .env file (default: .env in current directory)"
    )
    
    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()
    
    # Get credentials from args, env, or interactive
    api_id: Optional[int] = None
    api_hash: Optional[str] = None
    
    if args.api_id and args.api_hash:
        api_id = args.api_id
        api_hash = args.api_hash
    else:
        # Try environment variables
        creds = get_credentials_from_env()
        if creds:
            api_id, api_hash = creds
        else:
            # Fall back to interactive
            api_id, api_hash = get_credentials_interactive()
    
    # Generate session
    await generate_session(
        api_id=api_id,
        api_hash=api_hash,
        save_env=args.save_env,
        env_file=args.env_file
    )


if __name__ == "__main__":
    asyncio.run(main())
