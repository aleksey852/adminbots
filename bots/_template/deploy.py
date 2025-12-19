#!/usr/bin/env python3
"""
Bot Deployment Script — Подключение бота к Admin Panel.

Использование:
    python deploy.py --token YOUR_BOT_TOKEN [--panel-url URL] [--db-url URL]

Примеры:
    # Локальный деплой (автоматическое определение панели)
    python deploy.py --token 123456:ABC-DEF

    # С указанием URL панели
    python deploy.py --token 123456:ABC-DEF --panel-url http://panel.example.com

    # С кастомной БД
    python deploy.py --token 123456:ABC-DEF --db-url postgresql://user:pass@host/db
"""
import argparse
import asyncio
import os
import sys
import json
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def validate_token(token: str) -> dict:
    """Validate bot token and get bot info"""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    
    try:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        me = await bot.get_me()
        await bot.session.close()
        return {
            "id": me.id,
            "username": me.username,
            "first_name": me.first_name,
            "is_bot": me.is_bot
        }
    except Exception as e:
        raise ValueError(f"Invalid token: {e}")


async def register_with_panel(panel_url: str, bot_info: dict, manifest: dict, bot_path: str, db_url: str = None):
    """Register bot with Admin Panel"""
    import httpx
    
    payload = {
        "token": bot_info.get("token"),
        "name": manifest.get("display_name", bot_info.get("first_name")),
        "type": "custom",
        "manifest": manifest,
        "manifest_path": bot_path,
        "database_url": db_url
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{panel_url.rstrip('/')}/api/bots/connect",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 409:
                print("⚠️  Bot already registered. Updating connection...")
                # Try to update existing bot
                response = await client.put(
                    f"{panel_url.rstrip('/')}/api/bots/reconnect",
                    json=payload
                )
                if response.status_code == 200:
                    return response.json()
                raise Exception(f"Failed to reconnect: {response.text}")
            else:
                raise Exception(f"Registration failed: {response.status_code} - {response.text}")
        except httpx.ConnectError:
            raise Exception(f"Cannot connect to panel at {panel_url}")


async def create_database(db_name: str, base_url: str) -> str:
    """Create a new database for the bot"""
    import asyncpg
    import urllib.parse
    
    parsed = urllib.parse.urlparse(base_url)
    
    # Connect to postgres (default db) to create new database
    conn = await asyncpg.connect(f"{parsed.scheme}://{parsed.netloc}/postgres")
    try:
        # Check if database exists
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            print(f"✅ Created database: {db_name}")
        else:
            print(f"ℹ️  Database already exists: {db_name}")
    finally:
        await conn.close()
    
    return f"{parsed.scheme}://{parsed.netloc}/{db_name}"


async def init_bot_schema(db_url: str):
    """Initialize bot database schema"""
    import asyncpg
    
    conn = await asyncpg.connect(db_url)
    try:
        # Create essential tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_blocked BOOLEAN DEFAULT FALSE,
                is_admin BOOLEAN DEFAULT FALSE,
                registered_at TIMESTAMP DEFAULT NOW(),
                last_active TIMESTAMP DEFAULT NOW(),
                extra_data JSONB DEFAULT '{}'::jsonb
            );
            
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                direction TEXT NOT NULL,
                content TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
            
            CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_users_registered_at ON users(registered_at);
        """)
        print("✅ Database schema initialized")
    finally:
        await conn.close()


def load_manifest(bot_path: str) -> dict:
    """Load bot manifest.json"""
    manifest_path = os.path.join(bot_path, 'manifest.json')
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest.json not found in {bot_path}")
    
    with open(manifest_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_env_file(bot_path: str, bot_id: int, db_url: str, panel_url: str):
    """Save .env file with bot configuration"""
    env_path = os.path.join(bot_path, '.env')
    
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(f"# Auto-generated by deploy.py\n")
        f.write(f"BOT_ID={bot_id}\n")
        f.write(f"DATABASE_URL={db_url}\n")
        f.write(f"PANEL_URL={panel_url}\n")
    
    print(f"✅ Saved configuration to {env_path}")


async def deploy(args):
    """Main deployment function"""
    bot_path = os.path.dirname(os.path.abspath(__file__))
    
    print("🚀 Starting bot deployment...\n")
    
    # 1. Load manifest
    print("📋 Loading manifest...")
    try:
        manifest = load_manifest(bot_path)
        print(f"   Name: {manifest.get('display_name', manifest.get('name'))}")
        print(f"   Version: {manifest.get('version')}")
        print(f"   Modules: {', '.join(manifest.get('modules', []))}")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    # 2. Validate token
    print("\n🔑 Validating bot token...")
    try:
        bot_info = await validate_token(args.token)
        bot_info["token"] = args.token
        print(f"   Bot: @{bot_info['username']} ({bot_info['first_name']})")
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    # 3. Setup database
    if args.db_url:
        db_url = args.db_url
        print(f"\n💾 Using provided database: {db_url[:50]}...")
    else:
        print("\n💾 Creating database...")
        db_name = f"bot_{manifest.get('name', 'custom')}_{bot_info['id']}"
        # Use environment variable or default
        base_db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost')
        db_url = await create_database(db_name, base_db_url)
    
    # 4. Initialize schema
    print("\n📊 Initializing database schema...")
    await init_bot_schema(db_url)
    
    # 5. Register with panel (if panel_url provided)
    if args.panel_url:
        print(f"\n📡 Registering with Admin Panel...")
        try:
            result = await register_with_panel(
                args.panel_url, bot_info, manifest, bot_path, db_url
            )
            bot_id = result.get('bot_id')
            print(f"   Registered with ID: {bot_id}")
            
            # Save configuration
            save_env_file(bot_path, bot_id, db_url, args.panel_url)
        except Exception as e:
            print(f"⚠️  Panel registration failed: {e}")
            print("   Bot will run in standalone mode.")
    else:
        print("\n⚠️  No panel URL provided. Running in standalone mode.")
        bot_id = bot_info['id']
    
    print("\n" + "=" * 50)
    print("✅ Deployment complete!")
    print("=" * 50)
    print(f"\n📌 Bot: @{bot_info['username']}")
    print(f"📌 Database: {db_url}")
    if args.panel_url:
        print(f"📌 Panel: {args.panel_url}")
    
    print("\n🚀 To start the bot, run:")
    print(f"   python -m bots.{manifest.get('name')} --token {args.token[:10]}...")
    
    return {"bot_id": bot_id, "db_url": db_url}


def main():
    parser = argparse.ArgumentParser(
        description='Deploy bot to Admin Panel',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--token', '-t',
        required=True,
        help='Telegram Bot Token (from @BotFather)'
    )
    parser.add_argument(
        '--panel-url', '-p',
        help='Admin Panel URL (e.g., http://localhost:8000)'
    )
    parser.add_argument(
        '--db-url', '-d',
        help='PostgreSQL database URL (auto-created if not provided)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate only, do not deploy'
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("🔍 Dry run mode - validating only...")
        asyncio.run(validate_token(args.token))
        print("✅ Token is valid")
        return
    
    asyncio.run(deploy(args))


if __name__ == "__main__":
    main()
