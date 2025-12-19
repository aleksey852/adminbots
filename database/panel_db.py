"""
Panel Database Layer - Manages admin panel's own database
Contains: bot_registry, panel_users
Separate from bot databases for independence
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, Any, List, Dict
from datetime import datetime
import asyncpg
import json
from database.bot_db import DBWrapper

logger = logging.getLogger(__name__)

_panel_pool = None


async def init_panel_db(database_url: str):
    """Initialize panel database with connection pool"""
    global _panel_pool
    
    logger.info("Connecting to Panel Database...")
    _panel_pool = await asyncpg.create_pool(
        database_url,
        min_size=2,
        max_size=10,
        max_inactive_connection_lifetime=300,
        command_timeout=30,
    )
    logger.info("Panel database pool initialized")
    
    await _create_panel_schema()


async def close_panel_db():
    """Close panel database pool"""
    global _panel_pool
    if _panel_pool:
        await _panel_pool.close()
        _panel_pool = None
        logger.info("Panel database pool closed")


@asynccontextmanager
async def get_panel_connection():
    """Get connection from panel database pool"""
    if not _panel_pool:
        raise RuntimeError("Panel database pool not initialized")
    
    conn = await asyncio.wait_for(_panel_pool.acquire(), timeout=10.0)
    try:
        yield DBWrapper(conn)
    finally:
        await _panel_pool.release(conn)


# Remove PanelDBWrapper (using shared DBWrapper)


async def _create_panel_schema():
    """Create panel-only tables"""
    async with get_panel_connection() as db:
        # Bot Registry - stores all bots and their database URLs
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_registry (
                id SERIAL PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'receipt',
                database_url TEXT NOT NULL,
                manifest_path TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                admin_ids BIGINT[] DEFAULT '{}',
                enabled_modules TEXT[] DEFAULT '{"registration", "user_profile", "faq", "support"}',
                created_at TIMESTAMP DEFAULT NOW(),
                archived_at TIMESTAMP,
                archived_by TEXT
            );
        """)
        
        # Add manifest_path column if not exists (migration)
        await db.execute("""
            DO $$ 
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='bot_registry' AND column_name='manifest_path') THEN
                    ALTER TABLE bot_registry ADD COLUMN manifest_path TEXT;
                END IF;
            END $$;
        """)
        
        # Panel Users - admin panel access control
        await db.execute("""
            CREATE TABLE IF NOT EXISTS panel_users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'admin',
                created_at TIMESTAMP DEFAULT NOW(),
                last_login TIMESTAMP
            );
        """)

        # Module Settings - Stores JSON configuration for modules per bot
        await db.execute("""
            CREATE TABLE IF NOT EXISTS module_settings (
                bot_id INTEGER NOT NULL REFERENCES bot_registry(id) ON DELETE CASCADE,
                module_name TEXT NOT NULL,
                settings JSONB DEFAULT '{}'::jsonb,
                updated_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (bot_id, module_name)
            );
        """)


        
        # Indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_bot_registry_active ON bot_registry(is_active) WHERE archived_at IS NULL")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_bot_registry_token ON bot_registry(token)")
        
        logger.info("Panel schema initialized")


# === Bot Registry Methods ===

def escape_like(text: Optional[str]) -> str:
    """Escape special characters for LIKE queries"""
    if not text: return ""
    return str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

async def get_active_bots() -> List[Dict]:
    """Get only active (non-archived) bots"""
    async with get_panel_connection() as db:
        return await db.fetch("SELECT * FROM bot_registry WHERE is_active = TRUE AND archived_at IS NULL ORDER BY created_at DESC")

async def get_all_bots(include_archived: bool = False):
    async with get_panel_connection() as db:
        if include_archived:
            return await db.fetch("SELECT * FROM bot_registry ORDER BY created_at DESC")
        return await get_active_bots()

async def get_bot_by_id(bot_id: int):
    async with get_panel_connection() as db:
        return await db.fetchrow("SELECT * FROM bot_registry WHERE id = $1", bot_id)

async def get_bot_by_token(token: str):
    async with get_panel_connection() as db:
        return await db.fetchrow("SELECT * FROM bot_registry WHERE token = $1", token)

async def register_bot(token: str, name: str, bot_type: str, database_url: str, admin_ids: List[int] = None):
    async with get_panel_connection() as db:
        return await db.fetchval("INSERT INTO bot_registry (token, name, type, database_url, admin_ids) VALUES ($1, $2, $3, $4, $5) RETURNING id", token, name, bot_type, database_url, admin_ids or [])

# Whitelist of allowed fields for dynamic updates
ALLOWED_BOT_FIELDS = {'token', 'name', 'type', 'database_url', 'manifest_path', 'is_active', 'admin_ids', 'enabled_modules', 'archived_at', 'archived_by'}

async def update_bot(bot_id: int, **kwargs):
    """Update bot registry record"""
    if not kwargs: return False
    async with get_panel_connection() as db:
        fields = []
        vals = []
        idx = 1
        for k, v in kwargs.items():
            if k not in ALLOWED_BOT_FIELDS:
                logger.warning(f"Attempted to update non-whitelisted bot field: {k}")
                continue
            fields.append(f"{k} = ${idx}")
            vals.append(v)
            idx += 1
        if not fields:
            return False
        vals.append(bot_id)
        query = f"UPDATE bot_registry SET {', '.join(fields)} WHERE id = ${len(vals)}"
        return "UPDATE 1" in await db.execute(query, *vals)

async def delete_bot_registry(bot_id: int):
    async with get_panel_connection() as db:
        return "DELETE 1" in await db.execute("DELETE FROM bot_registry WHERE id = $1", bot_id)

async def archive_bot(bot_id: int, archived_by: str) -> bool:
    """Archive a bot (soft delete)"""
    return await update_bot(bot_id, is_active=False, archived_at=datetime.now(), archived_by=archived_by)

# === Bot Admins ===

async def get_bot_admins(bot_id: int) -> List[int]:
    """Get list of admin telegram_ids for a bot"""
    bot = await get_bot_by_id(bot_id)
    return list(bot['admin_ids']) if bot and bot['admin_ids'] else []

async def is_bot_admin(telegram_id: int, bot_id: int) -> bool:
    """Check if user is admin for specific bot"""
    import config
    if telegram_id in (config.ADMIN_IDS or []): return True
    admins = await get_bot_admins(bot_id)
    return telegram_id in (admins or [])

# === Module Helpers ===

async def get_bot_enabled_modules(bot_id: int) -> List[str]:
    """Get list of enabled modules for a bot"""
    bot = await get_bot_by_id(bot_id)
    if bot and bot.get('enabled_modules'):
        return list(bot['enabled_modules'])
    return ['core', 'registration', 'receipts', 'promo', 'admin']

async def update_bot_modules(bot_id: int, modules: List[str]) -> bool:
    """Update enabled modules for a bot"""
    return await update_bot(bot_id, enabled_modules=modules)

async def update_bot_admins_array(bot_id: int, admin_ids: List[int]) -> bool:
    """Update admin_ids array for a bot"""
    return await update_bot(bot_id, admin_ids=admin_ids)

# === Panel Users Methods ===

async def get_panel_user(username: str):
    async with get_panel_connection() as db: return await db.fetchrow("SELECT * FROM panel_users WHERE username = $1", username)

async def get_panel_user_by_id(user_id: int):
    async with get_panel_connection() as db: return await db.fetchrow("SELECT * FROM panel_users WHERE id = $1", user_id)

async def get_all_panel_users():
    async with get_panel_connection() as db: return await db.fetch("SELECT id, username, role, created_at, last_login FROM panel_users ORDER BY created_at")

async def create_panel_user(username: str, password_hash: str, role: str = 'admin'):
    async with get_panel_connection() as db: return await db.fetchval("INSERT INTO panel_users (username, password_hash, role) VALUES ($1, $2, $3) RETURNING id", username, password_hash, role)

# Whitelist of allowed fields for panel user updates
ALLOWED_PANEL_USER_FIELDS = {'username', 'password_hash', 'role', 'last_login'}

async def update_panel_user(user_id: int, **kwargs):
    if not kwargs: return False
    async with get_panel_connection() as db:
        fields = []
        vals = []
        idx = 1
        for k, v in kwargs.items():
            if k not in ALLOWED_PANEL_USER_FIELDS:
                logger.warning(f"Attempted to update non-whitelisted panel_user field: {k}")
                continue
            fields.append(f"{k} = ${idx}")
            vals.append(v)
            idx += 1
        if not fields:
            return False
        vals.append(user_id)
        query = f"UPDATE panel_users SET {', '.join(fields)} WHERE id = ${len(vals)}"
        return "UPDATE 1" in await db.execute(query, *vals)

async def delete_panel_user(user_id: int):
    async with get_panel_connection() as db: return "DELETE 1" in await db.execute("DELETE FROM panel_users WHERE id = $1", user_id)

async def update_panel_user_login(user_id: int):
    async with get_panel_connection() as db: await db.execute("UPDATE panel_users SET last_login = NOW() WHERE id = $1", user_id)

async def count_superadmins():
    async with get_panel_connection() as db: return await db.fetchval("SELECT COUNT(*) FROM panel_users WHERE role = 'superadmin'")

async def ensure_initial_superadmin(username: str, password_hash: str):
    """Create initial superadmin if no panel users exist"""
    async with get_panel_connection() as db:
        count = await db.fetchval("SELECT COUNT(*) FROM panel_users")
        if count == 0:
            await db.execute(
                "INSERT INTO panel_users (username, password_hash, role) VALUES ($1, $2, 'superadmin')",
                username, password_hash
            )
            logger.info(f"Created initial superadmin user: {username}")

# === Module Settings Methods ===

async def get_module_settings(bot_id: int, module_name: str) -> Dict[str, Any]:
    """Get settings for a specific module"""
    async with get_panel_connection() as db:
        row = await db.fetchrow(
            "SELECT settings FROM module_settings WHERE bot_id = $1 AND module_name = $2",
            bot_id, module_name
        )
        return json.loads(row['settings']) if row else {}

async def set_module_settings(bot_id: int, module_name: str, settings: Dict[str, Any]):
    """Save settings for a module"""
    import json
    async with get_panel_connection() as db:
        await db.execute("""
            INSERT INTO module_settings (bot_id, module_name, settings, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (bot_id, module_name) 
            DO UPDATE SET settings = $3, updated_at = NOW()
        """, bot_id, module_name, json.dumps(settings))

async def get_all_module_settings(bot_id: int) -> Dict[str, Dict]:
    """Get all module settings for a bot"""
    async with get_panel_connection() as db:
        rows = await db.fetch("SELECT module_name, settings FROM module_settings WHERE bot_id = $1", bot_id)
        return {row['module_name']: json.loads(row['settings']) for row in rows}

async def notify_reload_config(bot_id: int):
    """Send NOTIFY reload_config to wake up bot process"""
    async with get_panel_connection() as db:
        await db.execute("SELECT pg_notify('reload_config', $1)", str(bot_id))


# === Utility Methods ===

async def check_db_health() -> bool:
    """Check panel database connection health"""
    if not _panel_pool: return False
    try:
        async with get_panel_connection() as db:
            return await db.fetchval("SELECT 1") == 1
    except: return False

import re

DB_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,62}$')

async def create_bot_database(db_name: str, base_url: str) -> str:
    """Create a new database for a bot. Validates db_name to prevent injection."""
    import urllib.parse
    
    # Validate database name (PostgreSQL identifier rules)
    if not DB_NAME_PATTERN.match(db_name):
        raise ValueError(f"Invalid database name: {db_name}. Must be lowercase alphanumeric with underscores, starting with a letter.")
    
    parsed = urllib.parse.urlparse(base_url)
    conn = await asyncpg.connect(f"{parsed.scheme}://{parsed.netloc}/postgres")
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name):
            # Use quote_ident for extra safety (though we already validated)
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally: 
        await conn.close()
    return f"{parsed.scheme}://{parsed.netloc}/{db_name}"
