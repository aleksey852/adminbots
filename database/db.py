"""
Database layer with PostgreSQL connection pooling.
Simplified: consolidated table/index creation
+ PostgreSQL NOTIFY trigger for instant campaign notifications
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, Any, List, Dict
import config

logger = logging.getLogger(__name__)
_pool = None

# Timeout for acquiring connection from pool (seconds)
POOL_ACQUIRE_TIMEOUT = 10.0


async def init_db():
    """Initialize database with tables and indexes"""
    global _pool
    import asyncpg
    
    logger.info("Connecting to PostgreSQL...")
    _pool = await asyncpg.create_pool(
        config.DATABASE_URL,
        min_size=config.DB_POOL_MIN,
        max_size=config.DB_POOL_MAX,
        max_inactive_connection_lifetime=300,
        command_timeout=60,  # Timeout for individual queries
    )
    logger.info(f"PostgreSQL pool initialized (min={config.DB_POOL_MIN}, max={config.DB_POOL_MAX})")
    
    await _create_schema()


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed")


@asynccontextmanager
async def get_connection():
    """Get connection from pool with timeout"""
    if not _pool:
        raise RuntimeError("Database pool not initialized")
    
    try:
        # Add timeout to prevent indefinite waiting for connection
        conn = await asyncio.wait_for(
            _pool.acquire(),
            timeout=POOL_ACQUIRE_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.error(f"Failed to acquire DB connection within {POOL_ACQUIRE_TIMEOUT}s - pool may be exhausted")
        raise RuntimeError(f"Database connection pool timeout after {POOL_ACQUIRE_TIMEOUT}s")
    
    try:
        yield DBWrapper(conn)
    finally:
        await _pool.release(conn)


class DBWrapper:
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


async def _create_schema():
    """Create all tables and indexes with lock to prevent race conditions"""
    async with get_connection() as db:
        # Use advisory lock to prevent race condition when multiple workers start
        lock_acquired = await db.fetchval("SELECT pg_try_advisory_lock(12345)")
        
        if not lock_acquired:
            # Another worker is initializing, wait a bit and return
            logger.info("Schema initialization in progress by another worker, skipping...")
            return
        
        try:
            # 1. Create bots table with modular architecture support
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bots (
                    id SERIAL PRIMARY KEY,
                    token TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'receipt',
                    is_active BOOLEAN DEFAULT TRUE,
                    admin_ids BIGINT[] DEFAULT '{}',
                    enabled_modules TEXT[] DEFAULT '{"registration", "user_profile", "faq", "support"}',
                    archived_at TIMESTAMP,
                    archived_by TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

            # 2. Check/Insert default bot (Migration for existing data)
            # Default to "receipt" type as the current bot is a receipt bot
            default_bot_id = await db.fetchval("SELECT id FROM bots ORDER BY id LIMIT 1")
            
            if not default_bot_id and config.BOT_TOKEN:
                logger.info("Creating default bot from config...")
                default_bot_name = config.PROMO_NAME or "Default Bot"
                default_bot_id = await db.fetchval("""
                    INSERT INTO bots (token, name, type) 
                    VALUES ($1, $2, 'receipt')
                    ON CONFLICT (token) DO UPDATE SET token=EXCLUDED.token
                    RETURNING id
                """, config.BOT_TOKEN, default_bot_name)
            
            # Helper to add column safely
            async def add_column_safe(table, column, type_def):
                try:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {type_def}")
                except Exception as e:
                    logger.warning(f"Error adding column {column} to {table}: {e}")

            # 3. Create or Migrate Tables
            # Users
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    telegram_id BIGINT NOT NULL,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    registered_at TIMESTAMP DEFAULT NOW(),
                    is_blocked BOOLEAN DEFAULT FALSE
                    -- Constraint will be added/checked below
                );
            """)
            await add_column_safe("users", "bot_id", "INTEGER REFERENCES bots(id) ON DELETE CASCADE")
            
            if default_bot_id:
                await db.execute(f"UPDATE users SET bot_id = {default_bot_id} WHERE bot_id IS NULL")
            
            # Drop old constraint if exists (users_telegram_id_key) and create new partial or composite unique
            try:
                await db.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_telegram_id_key")
                await db.execute("""
                    DO $$ BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_telegram_id_bot_id_key') THEN
                            ALTER TABLE users ADD CONSTRAINT users_telegram_id_bot_id_key UNIQUE (telegram_id, bot_id);
                        END IF;
                    END $$;
                """)
            except Exception as e:
                logger.warning(f"Constraint migration error (users): {e}")

            # Jobs table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id SERIAL PRIMARY KEY,
                    bot_id BIGINT,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    progress INTEGER DEFAULT 0,
                    details JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)

            # Receipts
            await db.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    id SERIAL PRIMARY KEY,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id),
                    fiscal_drive_number TEXT,
                    fiscal_document_number TEXT,
                    fiscal_sign TEXT,
                    raw_qr TEXT,
                    status TEXT NOT NULL,
                    total_sum INTEGER DEFAULT 0,
                    product_name TEXT,
                    tickets INTEGER DEFAULT 1,
                    data JSONB,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(fiscal_drive_number, fiscal_document_number, fiscal_sign)
                );
            """)
            await add_column_safe("receipts", "bot_id", "INTEGER REFERENCES bots(id) ON DELETE CASCADE")
            if default_bot_id:
                await db.execute(f"UPDATE receipts SET bot_id = {default_bot_id} WHERE bot_id IS NULL")

            # Campaigns
            await db.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id SERIAL PRIMARY KEY,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    type TEXT NOT NULL,
                    content JSONB NOT NULL,
                    scheduled_for TIMESTAMP,
                    is_completed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    completed_at TIMESTAMP,
                    sent_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0
                );
            """)
            await add_column_safe("campaigns", "bot_id", "INTEGER REFERENCES bots(id) ON DELETE CASCADE")
            if default_bot_id:
                await db.execute(f"UPDATE campaigns SET bot_id = {default_bot_id} WHERE bot_id IS NULL")

            # Winners
            await db.execute("""
                CREATE TABLE IF NOT EXISTS winners (
                    id SERIAL PRIMARY KEY,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    campaign_id INTEGER REFERENCES campaigns(id),
                    user_id INTEGER REFERENCES users(id),
                    telegram_id BIGINT NOT NULL,
                    prize_name TEXT,
                    notified BOOLEAN DEFAULT FALSE,
                    notified_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(campaign_id, user_id)
                );
            """)
            await add_column_safe("winners", "bot_id", "INTEGER REFERENCES bots(id) ON DELETE CASCADE")
            if default_bot_id:
                await db.execute(f"UPDATE winners SET bot_id = {default_bot_id} WHERE bot_id IS NULL")

            # Promo Codes
            await db.execute("""
                CREATE TABLE IF NOT EXISTS promo_codes (
                    id SERIAL PRIMARY KEY,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    code TEXT NOT NULL,
                    status TEXT DEFAULT 'active', -- active, used
                    tickets INTEGER DEFAULT 1,
                    user_id INTEGER REFERENCES users(id),
                    used_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(bot_id, code)
                );
            """)

            # Broadcast Progress (depends on campaign, so implied, but good to ensure FK consistency if creating fresh)
             # (No bot_id needed here necessarily if 1:1 with campaign_id which has bot_id, but keeping structure simple)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_progress (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER UNIQUE REFERENCES campaigns(id),
                    last_user_id INTEGER DEFAULT 0,
                    sent_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)

            # Settings (Global vs Bot-Specific)
            # We will make settings bot-specific.
            # Old PK was key. New PK should be (key, bot_id).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (key, bot_id)
                );
            """)
            
            # Migration for settings
            # If 'settings' exists and has simple PK 'key', we need to alter it.
            # This is complex in pure SQL without deeper checks.
            # Check if bot_id column exists
            try:
                # Add column first
                await add_column_safe("settings", "bot_id", "INTEGER REFERENCES bots(id) ON DELETE CASCADE")
                
                # Check if older PK exists
                constraint_name = await db.fetchval("""
                    SELECT conname FROM pg_constraint 
                    WHERE conrelid = 'settings'::regclass AND contype = 'p';
                """)
                
                if constraint_name == 'settings_pkey':
                    # Check if bot_id is in PK
                    cols = await db.fetch("""
                        SELECT a.attname
                        FROM   pg_index i
                        JOIN   pg_attribute a ON a.attrelid = i.indrelid
                                            AND a.attnum = ANY(i.indkey)
                        WHERE  i.indrelid = 'settings'::regclass
                        AND    i.indisprimary;
                    """)
                    pk_cols = [r['attname'] for r in cols]
                    
                    if 'bot_id' not in pk_cols and default_bot_id:
                        await db.execute(f"UPDATE settings SET bot_id = {default_bot_id} WHERE bot_id IS NULL")
                        # Drop old PK
                        await db.execute(f"ALTER TABLE settings DROP CONSTRAINT {constraint_name}")
                        # Add new PK
                        await db.execute("ALTER TABLE settings ADD PRIMARY KEY (key, bot_id)")
                        logger.info("Migrated settings table to composite Primary Key")
            except Exception as e:
                logger.warning(f"Settings migration warning: {e}")

            # Messages (Same logic as Settings)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    key TEXT,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    text TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (key, bot_id)
                );
            """)
             # Migration for messages
            try:
                await add_column_safe("messages", "bot_id", "INTEGER REFERENCES bots(id) ON DELETE CASCADE")
                
                constraint_name = await db.fetchval("""
                    SELECT conname FROM pg_constraint 
                    WHERE conrelid = 'messages'::regclass AND contype = 'p';
                """)
                
                if constraint_name == 'messages_pkey':
                    cols = await db.fetch("""
                        SELECT a.attname
                        FROM   pg_index i
                        JOIN   pg_attribute a ON a.attrelid = i.indrelid
                                            AND a.attnum = ANY(i.indkey)
                        WHERE  i.indrelid = 'messages'::regclass
                        AND    i.indisprimary;
                    """)
                    pk_cols = [r['attname'] for r in cols]
                    
                    if 'bot_id' not in pk_cols and default_bot_id:
                        await db.execute(f"UPDATE messages SET bot_id = {default_bot_id} WHERE bot_id IS NULL")
                        await db.execute(f"ALTER TABLE messages DROP CONSTRAINT {constraint_name}")
                        await db.execute("ALTER TABLE messages ADD PRIMARY KEY (key, bot_id)")
                        logger.info("Migrated messages table to composite Primary Key")
            except Exception as e:
                logger.warning(f"Messages migration warning: {e}")

            
            # PostgreSQL NOTIFY function (unchanged usually, but let's re-ensure)
            await db.execute("""
                CREATE OR REPLACE FUNCTION notify_new_campaign() 
                RETURNS TRIGGER AS $$
                BEGIN
                    -- Do not notify future campaigns; scheduler will pick them up when due.
                    IF NEW.scheduled_for IS NULL OR NEW.scheduled_for <= NOW() THEN
                        PERFORM pg_notify('new_campaign', NEW.id::text);
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            trigger_exists = await db.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger 
                    WHERE tgname = 'campaign_insert_trigger' 
                    AND tgrelid = 'campaigns'::regclass
                )
            """)
            
            if not trigger_exists:
                await db.execute("""
                    CREATE TRIGGER campaign_insert_trigger
                    AFTER INSERT ON campaigns
                    FOR EACH ROW
                    EXECUTE FUNCTION notify_new_campaign();
                """)
            
            # Module Settings table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS module_settings (
                    id SERIAL PRIMARY KEY,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    module_name TEXT NOT NULL,
                    is_enabled BOOLEAN DEFAULT TRUE,
                    settings JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(bot_id, module_name)
                );
            """)
            
            # Bot Admins table (per-bot admin management)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_admins (
                    id SERIAL PRIMARY KEY,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    telegram_id BIGINT NOT NULL,
                    role TEXT DEFAULT 'admin',
                    added_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(bot_id, telegram_id)
                );
            """)
            
            # Data Migrations log table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS data_migrations (
                    id SERIAL PRIMARY KEY,
                    source_bot_id INTEGER REFERENCES bots(id),
                    target_bot_id INTEGER REFERENCES bots(id),
                    users_migrated INTEGER DEFAULT 0,
                    receipts_migrated INTEGER DEFAULT 0,
                    migrated_at TIMESTAMP DEFAULT NOW(),
                    migrated_by TEXT
                );
            """)
            
            # Panel Users table (Admin Panel access control)
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
            
            # Migrate first SuperAdmin from .env if table is empty
            panel_user_count = await db.fetchval("SELECT COUNT(*) FROM panel_users")
            if panel_user_count == 0 and config.ADMIN_PANEL_USER and config.ADMIN_PANEL_PASSWORD:
                import bcrypt
                password_hash = bcrypt.hashpw(
                    config.ADMIN_PANEL_PASSWORD.encode('utf-8'),
                    bcrypt.gensalt()
                ).decode('utf-8')
                await db.execute("""
                    INSERT INTO panel_users (username, password_hash, role)
                    VALUES ($1, $2, 'superadmin')
                    ON CONFLICT (username) DO NOTHING
                """, config.ADMIN_PANEL_USER, password_hash)
                logger.info(f"Created initial SuperAdmin user: {config.ADMIN_PANEL_USER}")
            
            # Migration for first SuperAdmin
            await add_column_safe("bots", "admin_ids", "BIGINT[] DEFAULT '{}'")
            await add_column_safe("bots", "enabled_modules", "TEXT[] DEFAULT '{\"registration\", \"user_profile\", \"faq\", \"support\"}'")
            await add_column_safe("bots", "archived_at", "TIMESTAMP")
            await add_column_safe("bots", "archived_by", "TEXT")
            
            # Manual Tickets table (for manual ticket assignment and final raffle)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS manual_tickets (
                    id SERIAL PRIMARY KEY,
                    bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    tickets INTEGER NOT NULL DEFAULT 1,
                    reason TEXT,
                    created_by TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            
            # Indexes
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_users_telegram_bot ON users(telegram_id, bot_id)",
                "CREATE INDEX IF NOT EXISTS idx_receipts_user ON receipts(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_receipts_bot ON receipts(bot_id)",
                "CREATE INDEX IF NOT EXISTS idx_campaigns_bot ON campaigns(bot_id)",
                "CREATE INDEX IF NOT EXISTS idx_campaigns_pending ON campaigns(is_completed, scheduled_for)",
                "CREATE INDEX IF NOT EXISTS idx_module_settings_bot ON module_settings(bot_id)",
                "CREATE INDEX IF NOT EXISTS idx_bot_admins_bot ON bot_admins(bot_id)",
                "CREATE INDEX IF NOT EXISTS idx_bot_admins_telegram ON bot_admins(telegram_id)",
                "CREATE INDEX IF NOT EXISTS idx_bots_active ON bots(is_active) WHERE archived_at IS NULL",
                "CREATE INDEX IF NOT EXISTS idx_manual_tickets_user ON manual_tickets(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_manual_tickets_bot ON manual_tickets(bot_id)",
            ]
            for idx in indexes:
                try:
                    await db.execute(idx)
                except:
                    pass
            
            logger.info(f"Database schema initialized/migrated. Default Bot ID: {default_bot_id}")
        
        finally:
            # Always release the lock
            await db.execute("SELECT pg_advisory_unlock(12345)")
