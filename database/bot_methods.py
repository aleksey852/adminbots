"""
Bot-specific database methods - No bot_id parameter needed
Each bot has its own database, methods operate on current context
Uses contextvars for async-safe context management
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Context variable for current bot database (async-safe)
_current_bot_db: ContextVar = ContextVar('current_bot_db', default=None)


def set_current_bot_db(db):
    """Set the current bot database context (async-safe)"""
    _current_bot_db.set(db)


def get_current_bot_db():
    """Get the current bot database context. Raises RuntimeError if not set."""
    db = _current_bot_db.get()
    if not db:
        raise RuntimeError(
            "No bot database context set. Ensure you're inside a bot_db_context() "
            "or that middleware has set the context via set_current_bot_db()."
        )
    return db


def get_current_bot_db_safe():
    """Get the current bot database context or None if not set (no exception)."""
    return _current_bot_db.get()


def is_bot_db_context_set() -> bool:
    """Check if bot database context is currently set."""
    return _current_bot_db.get() is not None


@asynccontextmanager
async def bot_db_context(bot_id: int):
    """Context manager to set current bot database (async-safe)"""
    from database.bot_db import bot_db_manager
    
    db = bot_db_manager.get(bot_id)
    if not db:
        # Try to connect if not registered
        logger.warning(f"Bot {bot_id} database not registered, attempting to connect...")
        raise RuntimeError(f"Bot {bot_id} database not registered. Call bot_db_manager.register() first.")
    
    token = _current_bot_db.set(db)
    try:
        yield db
    finally:
        _current_bot_db.reset(token)


# === User Methods ===

async def add_user(telegram_id: int, username: str, full_name: str, phone: str) -> int:
    """Add or update user"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval("""
            INSERT INTO users (telegram_id, username, full_name, phone)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (telegram_id) DO UPDATE 
            SET username = EXCLUDED.username, full_name = EXCLUDED.full_name, phone = EXCLUDED.phone
            RETURNING id
        """, telegram_id, username, full_name, phone)


async def get_user(telegram_id: int) -> Optional[Dict]:
    """Get user by telegram_id"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)


async def get_user_by_id(user_id: int) -> Optional[Dict]:
    """Get user by database ID"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)


async def get_user_with_stats(telegram_id: int) -> Optional[Dict]:
    """Get user with receipts/tickets stats"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchrow("""
            SELECT u.*,
                   COALESCE(COUNT(r.id) FILTER (WHERE r.status = 'valid'), 0) as valid_receipts,
                   COALESCE(COUNT(r.id), 0) as total_receipts,
                   COALESCE(SUM(r.tickets) FILTER (WHERE r.status = 'valid'), 0) as total_tickets
            FROM users u
            LEFT JOIN receipts r ON r.user_id = u.id
            WHERE u.telegram_id = $1
            GROUP BY u.id
        """, telegram_id)


async def get_users_paginated(page: int = 1, per_page: int = 50) -> List[Dict]:
    """Get paginated users list"""
    db = get_current_bot_db()
    offset = (page - 1) * per_page
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT u.*, 
                   COALESCE(SUM(r.tickets), 0) as total_tickets,
                   COUNT(r.id) as receipt_count
            FROM users u
            LEFT JOIN receipts r ON r.user_id = u.id AND r.status = 'valid'
            GROUP BY u.id
            ORDER BY u.registered_at DESC
            LIMIT $1 OFFSET $2
        """, per_page, offset)


async def get_total_users_count() -> int:
    """Get total users count"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users")


async def search_users(query: str) -> List[Dict]:
    """Search users by name, phone, username"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT * FROM users 
            WHERE full_name ILIKE $1 
               OR phone ILIKE $1 
               OR username ILIKE $1
               OR telegram_id::text LIKE $1
            LIMIT 100
        """, f"%{query}%")


async def block_user(user_id: int, blocked: bool = True) -> bool:
    """Block/unblock user"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        result = await conn.execute(
            "UPDATE users SET is_blocked = $1 WHERE id = $2",
            blocked, user_id
        )
        return "UPDATE 1" in result


async def update_username(telegram_id: int, username: str):
    """Update username"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        await conn.execute(
            "UPDATE users SET username = $1 WHERE telegram_id = $2",
            username, telegram_id
        )


async def get_all_users_for_broadcast() -> List[Dict]:
    """Get all non-blocked users for broadcast"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch(
            "SELECT id, telegram_id FROM users WHERE is_blocked = FALSE ORDER BY id"
        )


# === Receipt Methods ===

async def add_receipt(
    user_id: int,
    status: str,
    data: Dict = None,
    fiscal_drive_number: str = None,
    fiscal_document_number: str = None,
    fiscal_sign: str = None,
    total_sum: int = 0,
    raw_qr: str = None,
    product_name: str = None,
    tickets: int = 1
) -> Optional[int]:
    """Add a receipt"""
    db = get_current_bot_db()
    import json
    data_json = json.dumps(data) if data else None
    
    async with db.get_connection() as conn:
        return await conn.fetchval("""
            INSERT INTO receipts 
            (user_id, status, data, fiscal_drive_number, fiscal_document_number, 
             fiscal_sign, total_sum, raw_qr, product_name, tickets)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (fiscal_drive_number, fiscal_document_number, fiscal_sign) DO NOTHING
            RETURNING id
        """, user_id, status, data_json, fiscal_drive_number, fiscal_document_number,
        fiscal_sign, total_sum, raw_qr, product_name, tickets)


async def is_receipt_exists(fn: str, fd: str, fp: str) -> bool:
    """Check if receipt already exists"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM receipts 
                WHERE fiscal_drive_number = $1 
                AND fiscal_document_number = $2 
                AND fiscal_sign = $3
            )
        """, fn, fd, fp)


async def get_user_receipts_count(user_id: int) -> int:
    """Get valid receipts count for user"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM receipts WHERE user_id = $1 AND status = 'valid'",
            user_id
        )


async def get_user_tickets_count(user_id: int) -> int:
    """Get total tickets for user"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval(
            "SELECT COALESCE(SUM(tickets), 0) FROM receipts WHERE user_id = $1 AND status = 'valid'",
            user_id
        ) or 0


async def get_user_receipts(user_id: int, limit: int = 50, offset: int = 0) -> List[Dict]:
    """Get user's receipts"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch(
            "SELECT * FROM receipts WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            user_id, limit, offset
        )


# === Promo Code Methods ===

async def get_promo_code(code: str) -> Optional[Dict]:
    """Get promo code (case-insensitive)"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchrow(
            "SELECT * FROM promo_codes WHERE UPPER(code) = UPPER($1)",
            code
        )


async def use_promo_code(code_id: int, user_id: int) -> bool:
    """Mark promo code as used"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        result = await conn.execute("""
            UPDATE promo_codes 
            SET status = 'used', user_id = $1, used_at = NOW() 
            WHERE id = $2 AND status = 'active'
        """, user_id, code_id)
        return "UPDATE 1" in result


async def add_promo_codes(codes: List[str], tickets: int = 1) -> int:
    """Bulk add promo codes using batch insert for performance"""
    if not codes:
        return 0
    
    db = get_current_bot_db()
    # Prepare clean records
    records = [(code.strip().upper(), tickets, 'active') for code in codes if code.strip()]
    if not records:
        return 0
    
    async with db.get_connection() as conn:
        try:
            # Use executemany for batch insert with ON CONFLICT
            await conn.conn.executemany("""
                INSERT INTO promo_codes (code, tickets, status)
                VALUES ($1, $2, $3)
                ON CONFLICT (code) DO NOTHING
            """, records)
            return len(records)
        except Exception as e:
            logger.error(f"Bulk promo insert failed: {e}")
            # Fallback to individual inserts
            inserted = 0
            for code, tix, status in records:
                try:
                    await conn.execute("""
                        INSERT INTO promo_codes (code, tickets, status)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (code) DO NOTHING
                    """, code, tix, status)
                    inserted += 1
                except Exception:
                    pass
            return inserted


async def get_promo_stats() -> Dict:
    """Get promo codes statistics"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM promo_codes")
        used = await conn.fetchval("SELECT COUNT(*) FROM promo_codes WHERE status = 'used'")
        active = await conn.fetchval("SELECT COUNT(*) FROM promo_codes WHERE status = 'active'")
        return {"total": total, "used": used, "active": active}


async def get_promo_codes_paginated(limit: int = 50, offset: int = 0) -> List[Dict]:
    """Get promo codes paginated"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT pc.*, u.username, u.full_name 
            FROM promo_codes pc
            LEFT JOIN users u ON pc.user_id = u.id
            ORDER BY pc.created_at DESC LIMIT $1 OFFSET $2
        """, limit, offset)


# === Campaign Methods ===

async def add_campaign(campaign_type: str, content: Dict, scheduled_for: datetime = None) -> int:
    """Create a new campaign"""
    db = get_current_bot_db()
    import json
    async with db.get_connection() as conn:
        return await conn.fetchval("""
            INSERT INTO campaigns (type, content, scheduled_for)
            VALUES ($1, $2, $3)
            RETURNING id
        """, campaign_type, json.dumps(content), scheduled_for)


async def get_pending_campaigns() -> List[Dict]:
    """Get pending campaigns ready to execute"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT * FROM campaigns 
            WHERE is_completed = FALSE 
            AND (scheduled_for IS NULL OR scheduled_for <= NOW())
            ORDER BY id
        """)


async def mark_campaign_completed(campaign_id: int, sent: int = 0, failed: int = 0):
    """Mark campaign as completed"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        await conn.execute("""
            UPDATE campaigns 
            SET is_completed = TRUE, completed_at = NOW(), 
                sent_count = $2, failed_count = $3
            WHERE id = $1
        """, campaign_id, sent, failed)


# === Winner Methods ===

async def add_winner(campaign_id: int, user_id: int, telegram_id: int, prize_name: str) -> Optional[int]:
    """Add a winner"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval("""
            INSERT INTO winners (campaign_id, user_id, telegram_id, prize_name)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (campaign_id, user_id) DO NOTHING
            RETURNING id
        """, campaign_id, user_id, telegram_id, prize_name)


async def get_raffle_participants() -> List[Dict]:
    """Get all users eligible for raffle with their tickets"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT u.id, u.telegram_id, COALESCE(SUM(r.tickets), 0) as tickets
            FROM users u
            LEFT JOIN receipts r ON r.user_id = u.id AND r.status = 'valid'
            WHERE u.is_blocked = FALSE
            GROUP BY u.id
            HAVING COALESCE(SUM(r.tickets), 0) > 0
        """)


async def get_participants_count() -> int:
    """Get count of users with at least 1 ticket"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval("""
            SELECT COUNT(DISTINCT u.id)
            FROM users u
            JOIN receipts r ON r.user_id = u.id AND r.status = 'valid'
            WHERE u.is_blocked = FALSE
        """)


async def get_total_tickets_count() -> int:
    """Get total tickets in the pool"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval(
            "SELECT COALESCE(SUM(tickets), 0) FROM receipts WHERE status = 'valid'"
        ) or 0


# === Settings & Messages ===

async def get_setting(key: str, default: str = None) -> Optional[str]:
    """Get a setting value"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        value = await conn.fetchval(
            "SELECT value FROM settings WHERE key = $1", key
        )
        return value if value else default


async def set_setting(key: str, value: str):
    """Set a setting value"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()
        """, key, value)


async def get_message(key: str, default: str = "") -> str:
    """Get a message text"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        value = await conn.fetchval(
            "SELECT text FROM messages WHERE key = $1", key
        )
        return value if value else default


async def set_message(key: str, text: str):
    """Set a message text"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        await conn.execute("""
            INSERT INTO messages (key, text, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (key) DO UPDATE SET text = $2, updated_at = NOW()
        """, key, text)


async def get_all_settings() -> List[Dict]:
    """Get all settings"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("SELECT * FROM settings ORDER BY key")


async def get_all_messages() -> List[Dict]:
    """Get all messages"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("SELECT * FROM messages ORDER BY key")


# === Stats ===

async def get_stats() -> Dict:
    """Get bot statistics with all required fields for admin panel"""
    from datetime import datetime, timedelta
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        total_receipts = await conn.fetchval("SELECT COUNT(*) FROM receipts") or 0
        valid_receipts = await conn.fetchval("SELECT COUNT(*) FROM receipts WHERE status = 'valid'") or 0
        total_tickets = await conn.fetchval("SELECT COALESCE(SUM(tickets), 0) FROM receipts WHERE status = 'valid'") or 0
        participants = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM receipts WHERE status = 'valid'") or 0
        users_today = await conn.fetchval("SELECT COUNT(*) FROM users WHERE registered_at >= $1", today) or 0
        receipts_today = await conn.fetchval("SELECT COUNT(*) FROM receipts WHERE created_at >= $1", today) or 0
        total_winners = await conn.fetchval("SELECT COUNT(*) FROM winners") or 0
        blocked_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE") or 0
        
        return {
            "total_users": total_users,
            "total_receipts": total_receipts,
            "valid_receipts": valid_receipts,
            "total_tickets": total_tickets,
            "participants": participants,
            "users_today": users_today,
            "receipts_today": receipts_today,
            "total_winners": total_winners,
            "blocked_users": blocked_users,
        }


# === Broadcast Progress ===

async def get_broadcast_progress(campaign_id: int) -> Optional[Dict]:
    """Get broadcast progress"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchrow(
            "SELECT * FROM broadcast_progress WHERE campaign_id = $1",
            campaign_id
        )


async def save_broadcast_progress(campaign_id: int, last_user_id: int, sent: int, failed: int):
    """Save broadcast progress checkpoint"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        await conn.execute("""
            INSERT INTO broadcast_progress (campaign_id, last_user_id, sent_count, failed_count, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (campaign_id) DO UPDATE 
            SET last_user_id = $2, sent_count = $3, failed_count = $4, updated_at = NOW()
        """, campaign_id, last_user_id, sent, failed)


async def delete_broadcast_progress(campaign_id: int):
    """Delete broadcast progress after completion"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        await conn.execute("DELETE FROM broadcast_progress WHERE campaign_id = $1", campaign_id)


async def get_user_ids_paginated(last_id: int = 0, limit: int = 100) -> List[Dict]:
    """Get user IDs paginated for broadcast"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT id, telegram_id FROM users 
            WHERE is_blocked = FALSE AND id > $1 
            ORDER BY id LIMIT $2
        """, last_id, limit)


# === Raffle Helpers ===

async def get_participants_with_tickets() -> List[Dict]:
    """Get users with tickets for raffle (weighted pool)"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT u.id as user_id, u.telegram_id, u.full_name, u.username,
                   COALESCE(SUM(r.tickets), 0) as total_tickets
            FROM users u
            JOIN receipts r ON r.user_id = u.id AND r.status = 'valid'
            WHERE u.is_blocked = FALSE
            GROUP BY u.id
            HAVING COALESCE(SUM(r.tickets), 0) > 0
        """)


async def save_winners_atomic(campaign_id: int, winners_data: List[Dict]) -> int:
    """Save multiple winners atomically within a transaction"""
    if not winners_data:
        return 0
    
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        try:
            # Use transaction to ensure atomicity
            async with conn.conn.transaction():
                saved = 0
                for w in winners_data:
                    try:
                        result = await conn.execute("""
                            INSERT INTO winners (campaign_id, user_id, telegram_id, prize_name)
                            VALUES ($1, $2, $3, $4)
                            ON CONFLICT (campaign_id, user_id) DO NOTHING
                        """, campaign_id, w['user_id'], w['telegram_id'], w['prize_name'])
                        if "INSERT" in result:
                            saved += 1
                    except Exception as e:
                        logger.warning(f"Failed to save winner {w.get('user_id')}: {e}")
                return saved
        except Exception as e:
            logger.error(f"Transaction failed in save_winners_atomic: {e}")
            return 0


async def get_campaign_winners(campaign_id: int) -> List[Dict]:
    """Get winners for a campaign"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch(
            "SELECT * FROM winners WHERE campaign_id = $1",
            campaign_id
        )


async def mark_winner_notified(winner_id: int):
    """Mark winner as notified"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        await conn.execute(
            "UPDATE winners SET notified = TRUE, notified_at = NOW() WHERE id = $1",
            winner_id
        )


async def get_raffle_losers(campaign_id: int) -> List[Dict]:
    """Get users who participated but didn't win"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT DISTINCT u.id, u.telegram_id
            FROM users u
            JOIN receipts r ON r.user_id = u.id AND r.status = 'valid'
            WHERE u.is_blocked = FALSE
            AND u.id NOT IN (SELECT user_id FROM winners WHERE campaign_id = $1)
        """, campaign_id)


async def block_user_by_telegram_id(telegram_id: int):
    """Block user by telegram_id"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        await conn.execute(
            "UPDATE users SET is_blocked = TRUE WHERE telegram_id = $1",
            telegram_id
        )


async def get_user_wins(user_id: int) -> List[Dict]:
    """Get user's wins from raffles"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT w.*, c.completed_at FROM winners w
            JOIN campaigns c ON w.campaign_id = c.id
            WHERE w.user_id = $1 ORDER BY w.created_at DESC
        """, user_id)


async def get_recent_raffles_with_winners(limit: int = 5) -> List[Dict]:
    """Get recent raffles with their winners"""
    import json
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        campaigns = await conn.fetch("""
            SELECT * FROM campaigns WHERE type = 'raffle' AND is_completed = TRUE
            ORDER BY completed_at DESC LIMIT $1
        """, limit)
        
        if not campaigns:
            return []
        
        campaign_ids = [c['id'] for c in campaigns]
        placeholders = ','.join([f'${i+1}' for i in range(len(campaign_ids))])
        all_winners = await conn.fetch(f"""
            SELECT w.*, u.full_name, u.username, u.phone FROM winners w
            JOIN users u ON w.user_id = u.id WHERE w.campaign_id IN ({placeholders})
        """, *campaign_ids)
        
        winners_map = {}
        for w in all_winners:
            winners_map.setdefault(w['campaign_id'], []).append(dict(w))
        
        result = []
        for c in campaigns:
            c = dict(c)
            if isinstance(c.get('content'), str):
                c['content'] = json.loads(c['content'])
            c['prize_name'] = c.get('content', {}).get('prize', 'Розыгрыш')
            c['winners'] = winners_map.get(c['id'], [])
            result.append(c)
        return result


async def get_all_winners_for_export() -> List[Dict]:
    """Get all winners for CSV export"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT w.*, u.full_name, u.phone, u.username, c.created_at as raffle_date
            FROM winners w JOIN users u ON w.user_id = u.id
            JOIN campaigns c ON w.campaign_id = c.id 
            ORDER BY w.created_at DESC
        """)


# === Manual Tickets ===

async def add_manual_tickets(user_id: int, tickets: int, reason: str = None, created_by: str = None) -> int:
    """Add manual tickets to a user, returns new record ID"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval("""
            INSERT INTO manual_tickets (user_id, tickets, reason, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, user_id, tickets, reason, created_by)


async def get_user_manual_tickets(user_id: int) -> List[Dict]:
    """Get manual tickets history for a user"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT * FROM manual_tickets 
            WHERE user_id = $1 ORDER BY created_at DESC
        """, user_id)


async def get_user_total_tickets(user_id: int) -> int:
    """Get total tickets for user (receipts + manual + promo codes)"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval("""
            SELECT COALESCE(
                (SELECT SUM(tickets) FROM receipts WHERE user_id = $1 AND status = 'valid'), 0
            ) + COALESCE(
                (SELECT SUM(tickets) FROM manual_tickets WHERE user_id = $1), 0
            ) + COALESCE(
                (SELECT SUM(tickets) FROM promo_codes WHERE user_id = $1 AND status = 'used'), 0
            )
        """, user_id)


async def get_all_tickets_for_final_raffle() -> List[Dict]:
    """Get ALL tickets ever assigned for final raffle (receipts + manual + promo codes)"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT u.id as user_id, u.telegram_id, u.full_name, u.username,
                   COALESCE(r.receipt_tickets, 0) + COALESCE(m.manual_tickets, 0) + COALESCE(p.promo_tickets, 0) as total_tickets
            FROM users u
            LEFT JOIN (
                SELECT user_id, SUM(tickets) as receipt_tickets 
                FROM receipts WHERE status = 'valid' GROUP BY user_id
            ) r ON r.user_id = u.id
            LEFT JOIN (
                SELECT user_id, SUM(tickets) as manual_tickets 
                FROM manual_tickets GROUP BY user_id
            ) m ON m.user_id = u.id
            LEFT JOIN (
                SELECT user_id, SUM(tickets) as promo_tickets 
                FROM promo_codes WHERE status = 'used' GROUP BY user_id
            ) p ON p.user_id = u.id
            WHERE u.is_blocked = FALSE 
              AND (r.receipt_tickets > 0 OR m.manual_tickets > 0 OR p.promo_tickets > 0)
        """)


# === Job System ===

async def create_job(type: str, details: Dict = None) -> int:
    """Create a background job"""
    import json
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval("""
            INSERT INTO jobs (type, status, details, created_at, updated_at)
            VALUES ($1, 'pending', $2, NOW(), NOW())
            RETURNING id
        """, type, json.dumps(details or {}))


async def get_active_jobs() -> List[Dict]:
    """Get active (pending/processing) jobs"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT * FROM jobs WHERE status IN ('pending', 'processing')
            ORDER BY created_at DESC
        """)


async def get_job(job_id: int) -> Optional[Dict]:
    """Get job by ID"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)



# === Admin Panel Methods ===

async def get_user_detail(user_id: int) -> Optional[Dict]:
    """Get detailed user info with all stats"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if not user:
            return None
        
        user = dict(user)
        user['bot_id'] = db.bot_id # Inject bot_id for compatibility
        
        # Get receipt stats
        receipt_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_receipts,
                COUNT(CASE WHEN status = 'valid' THEN 1 END) as valid_receipts,
                COALESCE(SUM(CASE WHEN status = 'valid' THEN total_sum END), 0) as total_sum
            FROM receipts WHERE user_id = $1
        """, user_id)
        user.update(dict(receipt_stats))
        
        # Get wins
        wins = await conn.fetch("""
            SELECT w.*, c.created_at as raffle_date
            FROM winners w JOIN campaigns c ON w.campaign_id = c.id
            WHERE w.user_id = $1 ORDER BY w.created_at DESC
        """, user_id)
        user['wins'] = wins
        
        return user


async def update_user_fields(user_id: int, *, full_name: Optional[str] = None, phone: Optional[str] = None, username: Optional[str] = None):
    """Update selected user fields"""
    fields = []
    values = []
    
    if full_name is not None:
        fields.append("full_name = $" + str(len(values) + 1))
        values.append(full_name)
    if phone is not None:
        fields.append("phone = $" + str(len(values) + 1))
        values.append(phone)
    if username is not None:
        fields.append("username = $" + str(len(values) + 1))
        values.append(username)
    
    if not fields:
        return False
    
    values.append(user_id)
    
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        await conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ${len(values)}", *values)
    return True


async def get_stats_by_days(days: int = 14) -> List[Dict]:
    """Get statistics grouped by day for charts"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetch("""
            WITH date_series AS (
                SELECT generate_series(
                    CURRENT_DATE - ($1 || ' days')::interval,
                    CURRENT_DATE,
                    '1 day'::interval
                )::date AS day
            )
            SELECT 
                ds.day,
                COALESCE(u.user_count, 0) as users,
                COALESCE(r.receipt_count, 0) as receipts
            FROM date_series ds
            LEFT JOIN (
                SELECT DATE(registered_at) as day, COUNT(*) as user_count
                FROM users GROUP BY DATE(registered_at)
            ) u ON ds.day = u.day
            LEFT JOIN (
                SELECT DATE(created_at) as day, COUNT(*) as receipt_count
                FROM receipts WHERE status = 'valid' GROUP BY DATE(created_at)
            ) r ON ds.day = r.day
            ORDER BY ds.day
        """, str(days))


async def get_recent_campaigns(limit: int = 20) -> List[Dict]:
    """Get recent campaigns for admin panel"""
    import json
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        campaigns = await conn.fetch("""
            SELECT * FROM campaigns ORDER BY created_at DESC LIMIT $1
        """, limit)
        result = []
        for c in campaigns:
            c = dict(c)
            if isinstance(c.get('content'), str):
                try:
                    c['content'] = json.loads(c['content'])
                except:
                    pass
            result.append(c)
        return result


async def get_all_receipts_paginated(page: int = 1, per_page: int = 50) -> List[Dict]:
    """Get all receipts paginated with user info"""
    db = get_current_bot_db()
    offset = (page - 1) * per_page
    async with db.get_connection() as conn:
        return await conn.fetch("""
            SELECT r.*, u.full_name, u.username FROM receipts r
            JOIN users u ON r.user_id = u.id
            ORDER BY r.created_at DESC LIMIT $1 OFFSET $2
        """, per_page, offset)


async def get_total_receipts_count() -> int:
    """Get total receipts count"""
    db = get_current_bot_db()
    async with db.get_connection() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM receipts") or 0


async def get_user_receipts_detailed(user_id: int, limit: int = 50) -> List[Dict]:
    """Get user receipts with full details (alias for get_user_receipts but explicit name)"""
    return await get_user_receipts(user_id, limit)

