"""
Bot Database Layer - Per-bot database connections
Each bot has its own isolated database
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, Any, List, Dict
import asyncpg

logger = logging.getLogger(__name__)


class BotDatabase:
    """Manages connection pool for a single bot's database"""
    
    def __init__(self, bot_id: int, database_url: str):
        self.bot_id = bot_id
        self.database_url = database_url
        self._pool = None
    
    async def connect(self):
        """Initialize connection pool"""
        if self._pool:
            return
            
        logger.info(f"Bot {self.bot_id}: Connecting to database...")
        self._pool = await asyncpg.create_pool(
            self.database_url,
            min_size=2,
            max_size=10,
            max_inactive_connection_lifetime=300,
            command_timeout=60,
        )
        logger.info(f"Bot {self.bot_id}: Database pool initialized")
        
        await self._create_schema()
    
    async def close(self):
        """Close connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info(f"Bot {self.bot_id}: Database pool closed")
    
    @asynccontextmanager
    async def get_connection(self):
        """Get connection from pool"""
        if not self._pool:
            raise RuntimeError(f"Bot {self.bot_id}: Database pool not initialized")
        
        conn = await asyncio.wait_for(self._pool.acquire(), timeout=10.0)
        try:
            yield DBWrapper(conn)
        finally:
            await self._pool.release(conn)
    
    async def _create_schema(self):
        """Create bot-specific tables (no bot_id needed - each bot has own DB)"""
        async with self.get_connection() as db:
            # Users - simplified without bot_id
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    registered_at TIMESTAMP DEFAULT NOW(),
                    is_blocked BOOLEAN DEFAULT FALSE
                );
            """)
            
            # Receipts
            await db.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
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
            
            # Promo Codes
            await db.execute("""
                CREATE TABLE IF NOT EXISTS promo_codes (
                    id SERIAL PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    status TEXT DEFAULT 'active',
                    tickets INTEGER DEFAULT 1,
                    user_id INTEGER REFERENCES users(id),
                    used_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            
            # Campaigns
            await db.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id SERIAL PRIMARY KEY,
                    type TEXT NOT NULL,
                    content JSONB NOT NULL,
                    scheduled_for TIMESTAMP,
                    is_completed BOOLEAN DEFAULT FALSE,
                    status TEXT DEFAULT 'pending', -- pending, running, completed, cancelled, failed
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    completed_at TIMESTAMP,
                    sent_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0
                );
            """)
            
            # Migration: Add status column if not exists (for existing databases)
            try:
                await db.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'")
            except Exception as e:
                logger.warning(f"Migration warning: {e}")
            
            # Migration: Add error_message column if not exists
            try:
                await db.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS error_message TEXT")
            except Exception as e:
                logger.warning(f"Migration warning (error_message): {e}")
            
            # Winners - ticket-based (one ticket = one chance, user can win multiple times)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS winners (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    telegram_id BIGINT NOT NULL,
                    prize_name TEXT,
                    ticket_type TEXT,  -- 'receipt', 'promo', 'manual'
                    ticket_id INTEGER,  -- ID of the winning ticket record
                    ticket_value TEXT,  -- Display value (promo code or receipt identifier)
                    notified BOOLEAN DEFAULT FALSE,
                    notified_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(campaign_id, ticket_type, ticket_id)
                );
            """)
            
            # Migration: Add ticket columns to existing winners table
            for col in ['ticket_type TEXT', 'ticket_id INTEGER', 'ticket_value TEXT']:
                try:
                    await db.execute(f"ALTER TABLE winners ADD COLUMN IF NOT EXISTS {col}")
                except Exception as e:
                    logger.warning(f"Migration warning (winners.{col.split()[0]}): {e}")
            
            # Migration: Drop old unique constraint and create new one
            try:
                await db.execute("ALTER TABLE winners DROP CONSTRAINT IF EXISTS winners_campaign_id_user_id_key")
            except Exception as e:
                logger.warning(f"Migration warning (drop old constraint): {e}")
            
            try:
                await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_winners_campaign_ticket ON winners(campaign_id, ticket_type, ticket_id) WHERE ticket_type IS NOT NULL")
            except Exception as e:
                logger.warning(f"Migration warning (create new index): {e}")
            
            # Broadcast Progress
            await db.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_progress (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER UNIQUE REFERENCES campaigns(id) ON DELETE CASCADE,
                    last_user_id INTEGER DEFAULT 0,
                    sent_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)
            
            # Settings (bot-specific, no bot_id needed)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)
            
            # Messages
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    key TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)
            
            # Jobs
            await db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id SERIAL PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    progress INTEGER DEFAULT 0,
                    details JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)
            
            # Manual Tickets (for manual ticket assignment and final raffle)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS manual_tickets (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    tickets INTEGER NOT NULL DEFAULT 1,
                    reason TEXT,
                    created_by TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            
            # NOTIFY trigger for campaigns
            await db.execute("""
                CREATE OR REPLACE FUNCTION notify_new_campaign() 
                RETURNS TRIGGER AS $$
                BEGIN
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
            
            # Indexes
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_id)",
                "CREATE INDEX IF NOT EXISTS idx_receipts_user ON receipts(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_receipts_status ON receipts(status)",
                "CREATE INDEX IF NOT EXISTS idx_campaigns_pending ON campaigns(is_completed, scheduled_for)",
                "CREATE INDEX IF NOT EXISTS idx_promo_codes_code ON promo_codes(code)",
                "CREATE INDEX IF NOT EXISTS idx_promo_codes_status ON promo_codes(status)",
                "CREATE INDEX IF NOT EXISTS idx_manual_tickets_user ON manual_tickets(user_id)",
            ]
            for idx in indexes:
                try:
                    await db.execute(idx)
                except:
                    pass
            
            logger.info(f"Bot {self.bot_id}: Schema initialized")


class DBWrapper:
    """Consistent interface for asyncpg"""
    def __init__(self, conn):
        self.conn = conn
    
    async def execute(self, query: str, *args):
        return await self.conn.execute(query, *args)
    
    async def executemany(self, query: str, args_list):
        """Execute query with multiple argument sets (batch insert/update)"""
        return await self.conn.executemany(query, args_list)
    
    async def fetch(self, query: str, *args) -> List[Dict]:
        return [dict(r) for r in await self.conn.fetch(query, *args)]
    
    async def fetchrow(self, query: str, *args) -> Optional[Dict]:
        row = await self.conn.fetchrow(query, *args)
        return dict(row) if row else None
    
    async def fetchval(self, query: str, *args) -> Any:
        return await self.conn.fetchval(query, *args)


class BotDatabaseManager:
    """Manages database connections for all bots"""
    
    def __init__(self):
        self._databases: Dict[int, BotDatabase] = {}
    
    def register(self, bot_id: int, database_url: str):
        """Register a bot's database"""
        if bot_id not in self._databases:
            self._databases[bot_id] = BotDatabase(bot_id, database_url)
    
    async def connect(self, bot_id: int):
        """Connect to a bot's database"""
        if bot_id not in self._databases:
            raise RuntimeError(f"Bot {bot_id} not registered")
        await self._databases[bot_id].connect()
    
    async def connect_all(self):
        """Connect to all registered bot databases"""
        for bot_id in self._databases:
            await self.connect(bot_id)
    
    async def disconnect(self, bot_id: int):
        """Disconnect a specific bot's database"""
        db = self._databases.get(bot_id)
        if db:
            await db.close()
            del self._databases[bot_id]
            logger.info(f"Bot {bot_id}: Database disconnected")
    
    async def close_all(self):
        """Close all database connections"""
        for db in self._databases.values():
            await db.close()
        self._databases.clear()
    
    def get(self, bot_id: int) -> Optional[BotDatabase]:
        """Get a bot's database instance"""
        return self._databases.get(bot_id)
    
    @asynccontextmanager
    async def get_connection(self, bot_id: int):
        """Get connection for a specific bot"""
        db = self._databases.get(bot_id)
        if not db:
            raise RuntimeError(f"Bot {bot_id} database not registered")
        async with db.get_connection() as conn:
            yield conn


# Global instance
bot_db_manager = BotDatabaseManager()
