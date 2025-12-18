"""
Database methods for panel/bot management operations.
These work with the panel database (bots table, bot_admins, etc.)
Bot-specific data operations are in bot_methods.py
"""
import logging
from typing import List, Dict, Optional
from database.db import get_connection
import config

logger = logging.getLogger(__name__)


def escape_like(text: Optional[str]) -> str:
    """Escape special characters for LIKE queries"""
    if not text:
        return ""
    return str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# === Bot Management ===

async def get_bot_by_token(token: str) -> Optional[Dict]:
    """Get bot by token from panel database"""
    async with get_connection() as db:
        return await db.fetchrow("SELECT * FROM bots WHERE token = $1", token)


async def get_bot(bot_id: int) -> Optional[Dict]:
    """Get bot by ID from panel database"""
    async with get_connection() as db:
        return await db.fetchrow("SELECT * FROM bots WHERE id = $1", bot_id)


async def get_bot_config(bot_id: int) -> Dict:
    """Get bot settings from panel database"""
    async with get_connection() as db:
        rows = await db.fetch("SELECT key, value FROM settings WHERE bot_id = $1", bot_id)
        return {r['key']: r['value'] for r in rows}


# === Bot Admins ===

async def get_bot_admins(bot_id: int) -> List[int]:
    """Get list of admin telegram_ids for a bot"""
    async with get_connection() as db:
        # First check bot's admin_ids array
        bot = await db.fetchrow("SELECT admin_ids FROM bots WHERE id = $1", bot_id)
        admin_ids = list(bot['admin_ids']) if bot and bot['admin_ids'] else []
        
        # Also get from bot_admins table (more flexible management)
        rows = await db.fetch("SELECT telegram_id FROM bot_admins WHERE bot_id = $1", bot_id)
        for row in rows:
            if row['telegram_id'] not in admin_ids:
                admin_ids.append(row['telegram_id'])
        
        return admin_ids


async def add_bot_admin(bot_id: int, telegram_id: int, role: str = 'admin') -> bool:
    """Add admin to a bot"""
    async with get_connection() as db:
        try:
            await db.execute("""
                INSERT INTO bot_admins (bot_id, telegram_id, role)
                VALUES ($1, $2, $3)
                ON CONFLICT (bot_id, telegram_id) DO UPDATE SET role = $3
            """, bot_id, telegram_id, role)
            return True
        except Exception as e:
            logger.error(f"Failed to add bot admin: {e}")
            return False


async def remove_bot_admin(bot_id: int, telegram_id: int) -> bool:
    """Remove admin from a bot"""
    async with get_connection() as db:
        result = await db.execute(
            "DELETE FROM bot_admins WHERE bot_id = $1 AND telegram_id = $2",
            bot_id, telegram_id
        )
        return "DELETE 1" in result


async def is_bot_admin(telegram_id: int, bot_id: int) -> bool:
    """Check if user is admin for specific bot"""
    # First check super admins from config
    if telegram_id in config.ADMIN_IDS:
        return True
    
    admins = await get_bot_admins(bot_id)
    return telegram_id in admins


# === Bot Lifecycle ===

async def archive_bot(bot_id: int, archived_by: str) -> bool:
    """Archive a bot (soft delete)"""
    async with get_connection() as db:
        result = await db.execute("""
            UPDATE bots 
            SET is_active = FALSE, archived_at = NOW(), archived_by = $2
            WHERE id = $1 AND archived_at IS NULL
        """, bot_id, archived_by)
        return "UPDATE 1" in result


async def get_active_bots() -> List[Dict]:
    """Get only active (non-archived) bots"""
    async with get_connection() as db:
        return await db.fetch(
            "SELECT * FROM bots WHERE is_active = TRUE AND archived_at IS NULL"
        )


async def get_all_bots(include_archived: bool = False) -> List[Dict]:
    """Get all bots, optionally including archived"""
    async with get_connection() as db:
        if include_archived:
            return await db.fetch("SELECT * FROM bots ORDER BY created_at DESC")
        return await db.fetch(
            "SELECT * FROM bots WHERE archived_at IS NULL ORDER BY created_at DESC"
        )


# === Bot Modules ===

async def get_bot_enabled_modules(bot_id: int) -> List[str]:
    """Get list of enabled modules for a bot"""
    async with get_connection() as db:
        bot = await db.fetchrow("SELECT enabled_modules FROM bots WHERE id = $1", bot_id)
        if bot and bot['enabled_modules']:
            return list(bot['enabled_modules'])
        # Default modules
        return ['core', 'registration', 'receipts', 'promo', 'admin']


async def update_bot_modules(bot_id: int, modules: List[str]) -> bool:
    """Update enabled modules for a bot"""
    async with get_connection() as db:
        result = await db.execute(
            "UPDATE bots SET enabled_modules = $2 WHERE id = $1",
            bot_id, modules
        )
        return "UPDATE 1" in result


async def update_bot_admins_array(bot_id: int, admin_ids: List[int]) -> bool:
    """Update admin_ids array for a bot"""
    async with get_connection() as db:
        result = await db.execute(
            "UPDATE bots SET admin_ids = $2 WHERE id = $1",
            bot_id, admin_ids
        )
        return "UPDATE 1" in result


# === Health Check ===

async def check_db_health() -> bool:
    """Check database connection health"""
    try:
        async with get_connection() as db:
            return await db.fetchval("SELECT 1") == 1
    except Exception:
        return False
