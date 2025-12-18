"""
Panel Database Layer - Manages admin panel's own database
Contains: bot_registry, panel_users
Separate from bot databases for independence
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, Any, List, Dict
import asyncpg

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
        yield PanelDBWrapper(conn)
    finally:
        await _panel_pool.release(conn)


class PanelDBWrapper:
    """Consistent interface for asyncpg"""
    def __init__(self, conn):
        self.conn = conn
    
    async def execute(self, query: str, *args):
        return await self.conn.execute(query, *args)
    
    async def fetch(self, query: str, *args) -> List[Dict]:
        return [dict(r) for r in await self.conn.fetch(query, *args)]
    
    async def fetchrow(self, query: str, *args) -> Optional[Dict]:
        row = await self.conn.fetchrow(query, *args)
        return dict(row) if row else None
    
    async def fetchval(self, query: str, *args) -> Any:
        return await self.conn.fetchval(query, *args)


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
                is_active BOOLEAN DEFAULT TRUE,
                admin_ids BIGINT[] DEFAULT '{}',
                enabled_modules TEXT[] DEFAULT '{"registration", "user_profile", "faq", "support"}',
                created_at TIMESTAMP DEFAULT NOW(),
                archived_at TIMESTAMP,
                archived_by TEXT
            );
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
        
        # Indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_bot_registry_active ON bot_registry(is_active) WHERE archived_at IS NULL")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_bot_registry_token ON bot_registry(token)")
        
        logger.info("Panel schema initialized")


# === Bot Registry Methods ===

async def get_all_bots(include_archived: bool = False):
    async with get_panel_connection() as db:
        return await db.fetch("SELECT * FROM bot_registry" + ("" if include_archived else " WHERE archived_at IS NULL") + " ORDER BY created_at DESC")

async def get_bot_by_id(bot_id: int):
    async with get_panel_connection() as db: return await db.fetchrow("SELECT * FROM bot_registry WHERE id = $1", bot_id)

async def get_bot_by_token(token: str):
    async with get_panel_connection() as db: return await db.fetchrow("SELECT * FROM bot_registry WHERE token = $1", token)

async def register_bot(token: str, name: str, bot_type: str, database_url: str, admin_ids: List[int] = None):
    async with get_panel_connection() as db:
        return await db.fetchval("INSERT INTO bot_registry (token, name, type, database_url, admin_ids) VALUES ($1, $2, $3, $4, $5) RETURNING id", token, name, bot_type, database_url, admin_ids or [])

async def delete_bot_registry(bot_id: int):
    async with get_panel_connection() as db: return "DELETE 1" in await db.execute("DELETE FROM bot_registry WHERE id = $1", bot_id)

# === Panel Users Methods ===

async def get_panel_user(username: str):
    async with get_panel_connection() as db: return await db.fetchrow("SELECT * FROM panel_users WHERE username = $1", username)

async def get_panel_user_by_id(user_id: int):
    async with get_panel_connection() as db: return await db.fetchrow("SELECT * FROM panel_users WHERE id = $1", user_id)

async def get_all_panel_users():
    async with get_panel_connection() as db: return await db.fetch("SELECT id, username, role, created_at, last_login FROM panel_users ORDER BY created_at")

async def create_panel_user(username: str, password_hash: str, role: str = 'admin'):
    async with get_panel_connection() as db: return await db.fetchval("INSERT INTO panel_users (username, password_hash, role) VALUES ($1, $2, $3) RETURNING id", username, password_hash, role)

async def delete_panel_user(user_id: int):
    async with get_panel_connection() as db: return "DELETE 1" in await db.execute("DELETE FROM panel_users WHERE id = $1", user_id)

async def update_panel_user_login(user_id: int):
    async with get_panel_connection() as db: await db.execute("UPDATE panel_users SET last_login = NOW() WHERE id = $1", user_id)

async def count_superadmins():
    async with get_panel_connection() as db: return await db.fetchval("SELECT COUNT(*) FROM panel_users WHERE role = 'superadmin'")

async def create_bot_database(db_name: str, base_url: str) -> str:
    import urllib.parse
    parsed = urllib.parse.urlparse(base_url)
    conn = await asyncpg.connect(f"{parsed.scheme}://{parsed.netloc}/postgres")
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name):
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally: await conn.close()
    return f"{parsed.scheme}://{parsed.netloc}/{db_name}"
