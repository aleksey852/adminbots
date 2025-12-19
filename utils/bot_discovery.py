"""
Bot Templates Discovery — Сканирование и активация ботов из папки bots/.

Позволяет панели:
- Видеть все доступные шаблоны ботов
- Активировать бота введя токен
- Управлять активными ботами
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Path to bots directory (relative to project root)
BOTS_DIR = Path(__file__).parent.parent / "bots"


@dataclass
class BotTemplate:
    """Represents a bot template found in bots/ folder"""
    name: str
    display_name: str
    description: str
    version: str
    modules: List[str]
    path: str
    panel_features: Dict
    is_active: bool = False
    active_bot_id: Optional[int] = None


def scan_bot_templates() -> List[BotTemplate]:
    """
    Scan bots/ directory and return list of available templates.
    
    Skips:
    - _template (base template)
    - _base.py (utility file)
    - Folders without manifest.json
    
    Returns:
        List of BotTemplate objects
    """
    templates = []
    
    if not BOTS_DIR.exists():
        logger.warning(f"Bots directory not found: {BOTS_DIR}")
        return templates
    
    for item in BOTS_DIR.iterdir():
        # Skip non-directories, hidden folders, and utility files
        if not item.is_dir():
            continue
        if item.name.startswith('_') or item.name.startswith('.'):
            continue
        if item.name == '__pycache__':
            continue
        
        manifest_path = item / "manifest.json"
        if not manifest_path.exists():
            logger.debug(f"Skipping {item.name}: no manifest.json")
            continue
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            
            template = BotTemplate(
                name=manifest.get('name', item.name),
                display_name=manifest.get('display_name', item.name),
                description=manifest.get('description', ''),
                version=manifest.get('version', '1.0.0'),
                modules=manifest.get('modules', []),
                path=str(item.absolute()),
                panel_features=manifest.get('panel_features', {})
            )
            templates.append(template)
            
        except Exception as e:
            logger.error(f"Failed to load template {item.name}: {e}")
    
    return sorted(templates, key=lambda t: t.display_name)


async def get_templates_with_status() -> List[BotTemplate]:
    """
    Get templates with their activation status.
    
    Checks which templates have active bots in the database.
    """
    from database.panel_db import get_active_bots
    
    templates = scan_bot_templates()
    active_bots = await get_active_bots()
    
    # Map manifest_path to bot_id
    path_to_bot = {}
    for bot in active_bots:
        if bot.get('manifest_path'):
            path_to_bot[bot['manifest_path']] = bot
    
    # Update template status
    for template in templates:
        if template.path in path_to_bot:
            bot = path_to_bot[template.path]
            template.is_active = True
            template.active_bot_id = bot['id']
    
    return templates


async def activate_bot_template(
    template_path: str,
    token: str,
    admin_ids: List[int] = None,
    custom_name: str = None
) -> Dict:
    """
    Activate a bot template with the given token.
    
    Creates database, registers in panel, starts polling.
    
    Args:
        template_path: Absolute path to bot folder
        token: Telegram bot token
        admin_ids: List of admin telegram IDs
        custom_name: Custom name for the bot (displayed in panel)
    
    Returns:
        Dict with bot_id and status
    
    Raises:
        ValueError: If template not found or token invalid
    """
    import re
    import uuid
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from database.panel_db import (
        get_bot_by_token, register_bot, create_bot_database, 
        update_bot, get_panel_connection
    )
    from database.bot_db import bot_db_manager
    import config
    
    # Load manifest
    manifest_path = os.path.join(template_path, 'manifest.json')
    if not os.path.exists(manifest_path):
        raise ValueError(f"Template not found: {template_path}")
    
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    # Validate token
    if not token or ":" not in token:
        raise ValueError("Invalid token format")
    
    try:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        me = await bot.get_me()
        await bot.session.close()
    except Exception as e:
        raise ValueError(f"Invalid token: {e}")
    
    # Check if already registered
    existing = await get_bot_by_token(token)
    if existing:
        raise ValueError(f"Bot already registered with ID {existing['id']}")
    
    # Create database
    bot_name = manifest.get('name', 'bot')
    safe_name = re.sub(r'[^a-z0-9_]', '', bot_name.lower())[:20]
    db_name = f"bot_{safe_name}_{uuid.uuid4().hex[:6]}"
    
    db_url = await create_bot_database(db_name, config.DATABASE_URL)
    
    # Determine bot type from modules
    modules = manifest.get('modules', [])
    if 'receipts' in modules:
        bot_type = 'receipt'
    elif 'promo' in modules:
        bot_type = 'promo'
    else:
        bot_type = 'custom'
    
    # Use custom_name if provided, otherwise manifest display_name
    display_name = custom_name or manifest.get('display_name', me.first_name)
    
    # Register bot
    bot_id = await register_bot(
        token=token,
        name=display_name,
        bot_type=bot_type,
        database_url=db_url,
        admin_ids=admin_ids or []
    )
    
    # Set manifest path and modules
    enabled_modules = manifest.get('modules', ['core', 'registration'])
    await update_bot(bot_id, manifest_path=template_path, enabled_modules=enabled_modules)
    
    # Connect database
    bot_db_manager.register(bot_id, db_url)
    await bot_db_manager.connect(bot_id)
    
    # Initialize bot database schema
    db = bot_db_manager.get(bot_id)
    async with db.get_connection() as conn:
        # Create users table
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
                tickets INTEGER DEFAULT 0,
                extra_data JSONB DEFAULT '{}'::jsonb
            )
        """)
        
        # Create settings table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Create promo_codes if needed
        if 'promo' in modules:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS promo_codes (
                    id SERIAL PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    prize TEXT,
                    is_used BOOLEAN DEFAULT FALSE,
                    used_by INTEGER REFERENCES users(id),
                    used_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        
        # Create receipts if needed
        if 'receipts' in modules:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    file_id TEXT,
                    status TEXT DEFAULT 'pending',
                    tickets INTEGER DEFAULT 1,
                    reject_reason TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    reviewed_at TIMESTAMP
                )
            """)
        
        # Create winners table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS winners (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                prize TEXT,
                raffle_type TEXT DEFAULT 'main',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Create indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
    
    # Notify main process to reload bots
    async with get_panel_connection() as conn:
        await conn.execute("NOTIFY new_bot")
    
    logger.info(f"Activated bot template: {bot_name} → Bot ID {bot_id}")
    
    return {
        "bot_id": bot_id,
        "name": manifest.get('display_name', me.first_name),
        "username": me.username,
        "status": "activated"
    }


async def deactivate_bot(bot_id: int) -> bool:
    """
    Deactivate (archive) a bot.
    
    Does not delete data, just marks as inactive.
    """
    from database.panel_db import archive_bot
    return await archive_bot(bot_id, "panel")
