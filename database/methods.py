"""
Database methods - Simplified with reduced duplication
"""
import json
import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from database.db import get_connection
import config

logger = logging.getLogger(__name__)

# Stats cache
_stats_cache = {}
_stats_cache_time = 0.0
_stats_lock = asyncio.Lock()


def escape_like(text: Optional[str]) -> str:
    if not text: return ""
    return str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# === Bot Management ===

async def get_bot_by_token(token: str) -> Optional[Dict]:
    async with get_connection() as db:
        return await db.fetchrow("SELECT * FROM bots WHERE token = $1", token)

async def get_active_bots() -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("SELECT * FROM bots WHERE is_active = TRUE")

async def get_bot(bot_id: int) -> Optional[Dict]:
    async with get_connection() as db:
        return await db.fetchrow("SELECT * FROM bots WHERE id = $1", bot_id)

async def get_bot_config(bot_id: int) -> Dict:
    async with get_connection() as db:
        rows = await db.fetch("SELECT key, value FROM settings WHERE bot_id = $1", bot_id)
        return {r['key']: r['value'] for r in rows}

# === Users ===

async def add_user(telegram_id: int, username: str, full_name: str, phone: str, bot_id: int) -> int:
    async with get_connection() as db:
        # Use ON CONFLICT DO UPDATE to ensure we always get an ID back
        # even if the user was created concurrently
        return await db.fetchval("""
            INSERT INTO users (telegram_id, username, full_name, phone, bot_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (telegram_id, bot_id) DO UPDATE 
            SET username = EXCLUDED.username, 
                full_name = EXCLUDED.full_name
            RETURNING id
        """, telegram_id, username, full_name, phone, bot_id)


async def get_user(telegram_id: int, bot_id: int) -> Optional[Dict]:
    async with get_connection() as db:
        return await db.fetchrow("SELECT * FROM users WHERE telegram_id = $1 AND bot_id = $2", telegram_id, bot_id)


async def get_user_by_id(user_id: int) -> Optional[Dict]:
    async with get_connection() as db:
        return await db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)


async def get_user_by_username(username: str, bot_id: int) -> Optional[Dict]:
    async with get_connection() as db:
        return await db.fetchrow("SELECT * FROM users WHERE username ILIKE $1 AND bot_id = $2", username.lstrip('@'), bot_id)


async def get_user_by_phone(phone: str, bot_id: int) -> Optional[Dict]:
    async with get_connection() as db:
        clean = ''.join(filter(str.isdigit, phone))
        return await db.fetchrow("SELECT * FROM users WHERE phone LIKE $1 AND bot_id = $2", f"%{escape_like(clean)}%", bot_id)


async def get_user_with_stats(telegram_id: int, bot_id: int) -> Optional[Dict]:
    async with get_connection() as db:
        user = await db.fetchrow("SELECT * FROM users WHERE telegram_id = $1 AND bot_id = $2", telegram_id, bot_id)
        if not user:
            return None
        stats = await db.fetchrow("""
            SELECT COUNT(*) as total_receipts,
                   COUNT(CASE WHEN status = 'valid' THEN 1 END) as valid_receipts,
                   COALESCE(SUM(CASE WHEN status = 'valid' THEN tickets ELSE 0 END), 0) as total_tickets
            FROM receipts WHERE user_id = $1
        """, user['id'])
        return {**user, **stats}


async def update_username(telegram_id: int, username: str, bot_id: int):
    async with get_connection() as db:
        await db.execute("UPDATE users SET username = $1 WHERE telegram_id = $2 AND bot_id = $3", username, telegram_id, bot_id)


async def get_total_users_count(bot_id: int) -> int:
    async with get_connection() as db:
        return await db.fetchval("SELECT COUNT(*) FROM users WHERE bot_id = $1", bot_id)


async def get_all_user_ids(bot_id: int) -> List[int]:
    async with get_connection() as db:
        rows = await db.fetch("SELECT telegram_id FROM users WHERE is_blocked = FALSE AND bot_id = $1", bot_id)
        return [r['telegram_id'] for r in rows]


async def get_user_ids_paginated(bot_id: int, last_id: int = 0, limit: int = 1000) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT id, telegram_id FROM users 
            WHERE is_blocked = FALSE AND bot_id = $1 AND id > $2
            ORDER BY id LIMIT $3
        """, bot_id, last_id, limit)


async def get_users_paginated(bot_id: int, page: int = 1, per_page: int = 50) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT u.*, COUNT(r.id) as receipt_count
            FROM users u LEFT JOIN receipts r ON u.id = r.user_id AND r.status = 'valid'
            WHERE u.bot_id = $1
            GROUP BY u.id ORDER BY u.registered_at DESC
            LIMIT $2 OFFSET $3
        """, bot_id, per_page, (page - 1) * per_page)


# === Receipts ===

async def add_receipt(user_id: int, status: str, data: Dict, bot_id: int, **kwargs) -> int:
    fields = ['user_id', 'status', 'data', 'bot_id']
    values = [user_id, status, json.dumps(data), bot_id]
    placeholders = ['$1', '$2', '$3', '$4']
    
    for i, key in enumerate(['fiscal_drive_number', 'fiscal_document_number', 
                             'fiscal_sign', 'total_sum', 'product_name', 'raw_qr', 'tickets'], 5):
        if key in kwargs:
            fields.append(key)
            values.append(kwargs[key])
            placeholders.append(f'${i}')
    
    async with get_connection() as db:
        return await db.fetchval(f"""
            INSERT INTO receipts ({', '.join(fields)})
            VALUES ({', '.join(placeholders)}) RETURNING id
        """, *values)


async def is_receipt_exists(fn: str, fd: str, fp: str) -> bool:
    # Check globally or per bot? 
    # Usually receipts are unique by fiscal data globally.
    async with get_connection() as db:
        count = await db.fetchval("""
            SELECT COUNT(*) FROM receipts 
            WHERE fiscal_drive_number = $1 AND fiscal_document_number = $2 AND fiscal_sign = $3
        """, fn, fd, fp)
        return count > 0


async def get_user_receipts(user_id: int, limit: int = 10, offset: int = 0) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT * FROM receipts WHERE user_id = $1
            ORDER BY created_at DESC LIMIT $2 OFFSET $3
        """, user_id, limit, offset)


async def get_user_receipts_count(user_id: int) -> int:
    async with get_connection() as db:
        return await db.fetchval(
            "SELECT COUNT(*) FROM receipts WHERE user_id = $1 AND status = 'valid'", user_id)


async def get_user_tickets_count(user_id: int) -> int:
    """Get total tickets count for user (sum of all valid receipt tickets)"""
    async with get_connection() as db:
        result = await db.fetchval(
            "SELECT COALESCE(SUM(tickets), 0) FROM receipts WHERE user_id = $1 AND status = 'valid'", user_id)
        return result or 0


async def get_all_receipts_paginated(bot_id: int, page: int = 1, per_page: int = 50) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT r.*, u.full_name, u.username FROM receipts r
            JOIN users u ON r.user_id = u.id
            WHERE r.bot_id = $1
            ORDER BY r.created_at DESC LIMIT $2 OFFSET $3
        """, bot_id, per_page, (page - 1) * per_page)


async def get_total_receipts_count(bot_id: int) -> int:
    async with get_connection() as db:
        return await db.fetchval("SELECT COUNT(*) FROM receipts WHERE bot_id = $1", bot_id)


# === Campaigns ===

async def add_campaign(type: str, content: Dict, bot_id: int, scheduled_for: Optional[datetime] = None) -> int:
    async with get_connection() as db:
        return await db.fetchval("""
            INSERT INTO campaigns (type, content, bot_id, scheduled_for)
            VALUES ($1, $2, $3, $4) RETURNING id
        """, type, json.dumps(content), bot_id, scheduled_for)


async def get_pending_campaigns() -> List[Dict]:
    # Returns pending campaigns for ALL bots
    async with get_connection() as db:
        return await db.fetch("""
            SELECT * FROM campaigns 
            WHERE is_completed = FALSE AND (scheduled_for IS NULL OR scheduled_for <= NOW())
            ORDER BY created_at
        """)


async def mark_campaign_completed(campaign_id: int, sent: int = 0, failed: int = 0):
    async with get_connection() as db:
        await db.execute("""
            UPDATE campaigns 
            SET is_completed = TRUE, completed_at = NOW(), sent_count = $1, failed_count = $2
            WHERE id = $3
        """, sent, failed, campaign_id)


async def get_campaign(campaign_id: int) -> Optional[Dict]:
    async with get_connection() as db:
        c = await db.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)
        if c and isinstance(c.get('content'), str):
            c = dict(c)
            c['content'] = json.loads(c['content'])
        return c


# === Winners & Raffle ===

async def get_participants_count(bot_id: int) -> int:
    async with get_connection() as db:
        # Count distinct users in this bot who have valid receipts
        return await db.fetchval("""
            SELECT COUNT(DISTINCT r.user_id) 
            FROM receipts r
            JOIN users u ON r.user_id = u.id
            WHERE r.status = 'valid' AND r.bot_id = $1
        """, bot_id)


async def get_participants_with_ids(bot_id: int) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT DISTINCT u.id as user_id, u.telegram_id, u.full_name, u.username
            FROM users u JOIN receipts r ON u.id = r.user_id 
            WHERE r.status = 'valid' AND r.bot_id = $1
        """, bot_id)


async def get_participants_with_tickets(bot_id: int) -> List[Dict]:
    """Get participants with their total tickets count for weighted raffle"""
    async with get_connection() as db:
        return await db.fetch("""
            SELECT u.id as user_id, u.telegram_id, u.full_name, u.username,
                   COALESCE(SUM(r.tickets), 0) as total_tickets
            FROM users u 
            JOIN receipts r ON u.id = r.user_id 
            WHERE r.status = 'valid' AND r.bot_id = $1
            GROUP BY u.id, u.telegram_id, u.full_name, u.username
            HAVING SUM(r.tickets) > 0
        """, bot_id)


async def get_total_tickets_count(bot_id: int) -> int:
    """Get total number of tickets for raffle"""
    async with get_connection() as db:
        result = await db.fetchval("SELECT COALESCE(SUM(tickets), 0) FROM receipts WHERE status = 'valid' AND bot_id = $1", bot_id)
        return result or 0


async def get_raffle_losers(campaign_id: int, limit: int = 1000, offset: int = 0) -> List[Dict]:
    """Get participants who didn't win in the specified campaign"""
    async with get_connection() as db:
        # Determine bot_id from campaign
        bot_id = await db.fetchval("SELECT bot_id FROM campaigns WHERE id = $1", campaign_id)
        
        if not bot_id:
            return []

        return await db.fetch("""
            SELECT DISTINCT u.telegram_id
            FROM users u 
            JOIN receipts r ON u.id = r.user_id 
            WHERE r.status = 'valid' AND u.bot_id = $1
            AND u.id NOT IN (SELECT user_id FROM winners WHERE campaign_id = $2)
            LIMIT $3 OFFSET $4
        """, bot_id, campaign_id, limit, offset)


async def save_winners_atomic(campaign_id: int, winners_data: List[Dict], bot_id: int) -> int:
    """Save winners with advisory lock to prevent race conditions"""
    async with get_connection() as db:
        lock = await db.fetchval("SELECT pg_try_advisory_lock($1)", campaign_id)
        if not lock:
            return 0
        try:
            existing = await db.fetchval("SELECT COUNT(*) FROM winners WHERE campaign_id = $1", campaign_id)
            if existing > 0:
                return 0
            
            count = 0
            async with db.conn.transaction():
                for w in winners_data:
                    await db.execute("""
                        INSERT INTO winners (campaign_id, user_id, telegram_id, prize_name, bot_id)
                        VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING
                    """, campaign_id, w['user_id'], w['telegram_id'], w['prize_name'], bot_id)
                    count += 1
            return count
        finally:
            await db.execute("SELECT pg_advisory_unlock($1)", campaign_id)


async def get_unnotified_winners(campaign_id: int) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT w.*, c.content FROM winners w
            JOIN campaigns c ON w.campaign_id = c.id
            WHERE w.notified = FALSE AND w.campaign_id = $1
        """, campaign_id)


async def mark_winner_notified(winner_id: int):
    async with get_connection() as db:
        await db.execute("UPDATE winners SET notified = TRUE, notified_at = NOW() WHERE id = $1", winner_id)


async def get_campaign_winners(campaign_id: int) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT w.*, u.full_name, u.username FROM winners w
            JOIN users u ON w.user_id = u.id WHERE w.campaign_id = $1
        """, campaign_id)


async def get_recent_raffles_with_winners(bot_id: int, limit: int = 5) -> List[Dict]:
    async with get_connection() as db:
        campaigns = await db.fetch("""
            SELECT * FROM campaigns WHERE type = 'raffle' AND is_completed = TRUE AND bot_id = $1
            ORDER BY completed_at DESC LIMIT $2
        """, bot_id, limit)
        if not campaigns:
            return []
        
        campaign_ids = [c['id'] for c in campaigns]
        placeholders = ','.join([f'${i+1}' for i in range(len(campaign_ids))])
        all_winners = await db.fetch(f"""
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
            # Extract prize_name from content
            c['prize_name'] = c.get('content', {}).get('prize_name', 'Розыгрыш')
            c['winners'] = winners_map.get(c['id'], [])
            result.append(c)
        return result


async def get_all_winners_for_export(bot_id: int) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT w.*, u.full_name, u.phone, u.username, c.created_at as raffle_date
            FROM winners w JOIN users u ON w.user_id = u.id
            JOIN campaigns c ON w.campaign_id = c.id 
            WHERE w.bot_id = $1
            ORDER BY w.created_at DESC
        """, bot_id)


async def get_user_wins(user_id: int) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT w.*, c.completed_at FROM winners w
            JOIN campaigns c ON w.campaign_id = c.id
            WHERE w.user_id = $1 ORDER BY w.created_at DESC
        """, user_id)


# === Broadcast Progress ===

async def get_broadcast_progress(campaign_id: int) -> Optional[Dict]:
    async with get_connection() as db:
        return await db.fetchrow("SELECT * FROM broadcast_progress WHERE campaign_id = $1", campaign_id)


async def save_broadcast_progress(campaign_id: int, last_user_id: int, sent: int, failed: int):
    async with get_connection() as db:
        await db.execute("""
            INSERT INTO broadcast_progress (campaign_id, last_user_id, sent_count, failed_count)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (campaign_id) DO UPDATE 
            SET last_user_id = EXCLUDED.last_user_id, sent_count = EXCLUDED.sent_count,
                failed_count = EXCLUDED.failed_count, updated_at = NOW()
        """, campaign_id, last_user_id, sent, failed)


async def delete_broadcast_progress(campaign_id: int):
    async with get_connection() as db:
        await db.execute("DELETE FROM broadcast_progress WHERE campaign_id = $1", campaign_id)


# === Health & Stats ===

async def check_db_health() -> bool:
    try:
        async with get_connection() as db:
            return await db.fetchval("SELECT 1") == 1
    except:
        return False


async def get_stats(bot_id: int) -> Dict:
    global _stats_cache, _stats_cache_time
    
    # Cache key must include bot_id
    cache_key = f"stats_{bot_id}"
    
    if time.time() - _stats_cache_time < config.STATS_CACHE_TTL and cache_key in _stats_cache:
        return _stats_cache[cache_key].copy()
    
    async with _stats_lock:
        if time.time() - _stats_cache_time < config.STATS_CACHE_TTL and cache_key in _stats_cache:
            return _stats_cache[cache_key].copy()
        
        async with get_connection() as db:
            now = datetime.utcnow()
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_ago = now - timedelta(days=7)
            
            stats = {
                "total_users": await db.fetchval("SELECT COUNT(*) FROM users WHERE bot_id = $1", bot_id),
                "total_receipts": await db.fetchval("SELECT COUNT(*) FROM receipts WHERE bot_id = $1", bot_id),
                "valid_receipts": await db.fetchval("SELECT COUNT(*) FROM receipts WHERE status = 'valid' AND bot_id = $1", bot_id),
                "total_tickets": await db.fetchval("SELECT COALESCE(SUM(tickets), 0) FROM receipts WHERE status = 'valid' AND bot_id = $1", bot_id),
                "participants": await db.fetchval("SELECT COUNT(DISTINCT user_id) FROM receipts WHERE status = 'valid' AND bot_id = $1", bot_id),
                "users_today": await db.fetchval("SELECT COUNT(*) FROM users WHERE registered_at >= $1 AND bot_id = $2", today, bot_id),
                "users_24h": await db.fetchval("SELECT COUNT(*) FROM users WHERE registered_at >= $1 AND bot_id = $2", now - timedelta(hours=24), bot_id),
                "users_7d": await db.fetchval("SELECT COUNT(*) FROM users WHERE registered_at >= $1 AND bot_id = $2", week_ago, bot_id),
                "receipts_today": await db.fetchval("SELECT COUNT(*) FROM receipts WHERE created_at >= $1 AND bot_id = $2", today, bot_id),
                "receipts_24h": await db.fetchval("SELECT COUNT(*) FROM receipts WHERE created_at >= $1 AND bot_id = $2", now - timedelta(hours=24), bot_id),
                "receipts_7d": await db.fetchval("SELECT COUNT(*) FROM receipts WHERE created_at >= $1 AND bot_id = $2", week_ago, bot_id),
                "tickets_today": await db.fetchval("SELECT COALESCE(SUM(tickets), 0) FROM receipts WHERE status = 'valid' AND created_at >= $1 AND bot_id = $2", today, bot_id),
                "total_winners": await db.fetchval("SELECT COUNT(*) FROM winners WHERE bot_id = $1", bot_id),
                "total_campaigns": await db.fetchval("SELECT COUNT(*) FROM campaigns WHERE bot_id = $1", bot_id),
                "completed_campaigns": await db.fetchval("SELECT COUNT(*) FROM campaigns WHERE is_completed = TRUE AND bot_id = $1", bot_id),
            }
            stats["conversion"] = round((stats["participants"] / stats["total_users"] * 100) if stats["total_users"] else 0, 2)
            
            _stats_cache[cache_key] = stats
            _stats_cache_time = time.time()
            return stats.copy()


async def get_stats_by_days(bot_id: int, days: int = 14) -> List[Dict]:
    """Get statistics grouped by day for charts"""
    async with get_connection() as db:
        return await db.fetch("""
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
                FROM users WHERE bot_id = $2 GROUP BY DATE(registered_at)
            ) u ON ds.day = u.day
            LEFT JOIN (
                SELECT DATE(created_at) as day, COUNT(*) as receipt_count
                FROM receipts WHERE status = 'valid' AND bot_id = $2 GROUP BY DATE(created_at)
            ) r ON ds.day = r.day
            ORDER BY ds.day
        """, str(days), bot_id)


async def search_users(query: str, bot_id: int, limit: int = 20) -> List[Dict]:
    """Search users by name, username, phone or telegram_id"""
    async with get_connection() as db:
        clean_query = query.strip()
        
        # Try exact telegram_id match first
        if clean_query.isdigit():
            user = await db.fetchrow("""
                SELECT u.*, COUNT(r.id) as receipt_count
                FROM users u LEFT JOIN receipts r ON u.id = r.user_id AND r.status = 'valid'
                WHERE (u.telegram_id = $1 OR u.id = $1) AND u.bot_id = $2
                GROUP BY u.id
            """, int(clean_query), bot_id)
            if user:
                return [user]
        
        # Search by text
        search_pattern = f"%{escape_like(clean_query)}%"
        return await db.fetch("""
            SELECT u.*, COUNT(r.id) as receipt_count
            FROM users u LEFT JOIN receipts r ON u.id = r.user_id AND r.status = 'valid'
            WHERE (u.full_name ILIKE $1 
               OR u.username ILIKE $1 
               OR u.phone LIKE $2)
               AND u.bot_id = $3
            GROUP BY u.id
            ORDER BY u.registered_at DESC
            LIMIT $4
        """, search_pattern, f"%{escape_like(''.join(filter(str.isdigit, clean_query)))}%", bot_id, limit)


async def get_user_detail(user_id: int) -> Optional[Dict]:
    """Get detailed user info with all stats"""
    async with get_connection() as db:
        user = await db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if not user:
            return None
        
        user = dict(user)
        
        # Get receipt stats
        receipt_stats = await db.fetchrow("""
            SELECT 
                COUNT(*) as total_receipts,
                COUNT(CASE WHEN status = 'valid' THEN 1 END) as valid_receipts,
                COALESCE(SUM(CASE WHEN status = 'valid' THEN total_sum END), 0) as total_sum
            FROM receipts WHERE user_id = $1
        """, user_id)
        user.update(dict(receipt_stats))
        
        # Get wins
        wins = await db.fetch("""
            SELECT w.*, c.created_at as raffle_date
            FROM winners w JOIN campaigns c ON w.campaign_id = c.id
            WHERE w.user_id = $1 ORDER BY w.created_at DESC
        """, user_id)
        user['wins'] = wins
        
        return user


async def get_user_receipts_detailed(user_id: int, limit: int = 50) -> List[Dict]:
    """Get user receipts with full details"""
    async with get_connection() as db:
        return await db.fetch("""
            SELECT * FROM receipts WHERE user_id = $1
            ORDER BY created_at DESC LIMIT $2
        """, user_id, limit)


async def get_recent_campaigns(bot_id: int, limit: int = 20) -> List[Dict]:
    """Get recent campaigns for admin panel"""
    async with get_connection() as db:
        campaigns = await db.fetch("""
            SELECT * FROM campaigns WHERE bot_id = $1 ORDER BY created_at DESC LIMIT $2
        """, bot_id, limit)
        result = []
        for c in campaigns:
            c = dict(c)
            if isinstance(c.get('content'), str):
                c['content'] = json.loads(c['content'])
            result.append(c)
        return result


async def block_user(user_id: int, blocked: bool = True):
    """Block or unblock user"""
    async with get_connection() as db:
        await db.execute("UPDATE users SET is_blocked = $1 WHERE id = $2", blocked, user_id)


# === Promo Codes ===

async def add_promo_codes(bot_id: int, codes: List[str], tickets: int = 1) -> int:
    """Bulk add promo codes"""
    if not codes: return 0
    
    count = 0
    async with get_connection() as db:
        # We use a transaction for bulk insert
        async with db.conn.transaction():
            for code in codes:
                if not code.strip(): continue
                await db.execute("""
                    INSERT INTO promo_codes (bot_id, code, tickets)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (bot_id, code) DO NOTHING
                """, bot_id, code.strip(), tickets)
                count += 1
    return count


async def add_promo_codes_bulk(bot_id: int, codes_iterator, tickets: int = 1) -> int:
    """
    Bulk add promo codes using COPY and temp table for performance.
    codes_iterator: iterable (list or generator) yielding code strings.
    """
    async with get_connection() as db:
        # 1. Create temp table (unlogged for speed, drop on commit)
        # We use a random suffix to allow concurrent uploads if needed, 
        # but for simplicity and session isolation, generic name is fine if transaction isolated.
        # Actually in PG temp tables are session-private.
        await db.execute("CREATE TEMP TABLE IF NOT EXISTS promo_import_tmp (code TEXT) ON COMMIT DROP")
        
        # 2. Prepare records generator
        # asyncpg copy_records_to_table accepts an iterable (not async iterator directly usually).
        # We assume codes_iterator is already an iterable of strings or we convert it.
        # If it's an async generator, we might need to batch it.
        # For huge files, we receive an async stream. We should probably buffer/batch manually for copy.
        # But here let's assume valid iterable.
        
        # If input is async generator, we need to consume it or handle differently.
        # For simplicity, we'll accept a list of tuples for copy_records_to_table
        # OR we rely on caller to pass a list/generator.
        
        records = ((c.strip(),) for c in codes_iterator if c.strip())
        
        try:
            # COPY to temp table
            await db.conn.copy_records_to_table('promo_import_tmp', records=records)
            
            # 3. Insert from temp to main
            # We use ON CONFLICT to skip duplicates
            query = """
                INSERT INTO promo_codes (bot_id, code, tickets)
                SELECT $1, code, $2 FROM promo_import_tmp
                ON CONFLICT (bot_id, code) DO NOTHING
            """
            result = await db.execute(query, bot_id, tickets)
            
            # Parse inserted count from "INSERT 0 123"
            try:
                count = int(result.split()[-1])
            except:
                count = 0
                
            return count
            
        except Exception as e:
            logger.error(f"Bulk copy error: {e}")
            raise
        finally:
            # Explicit drop just in case, though ON COMMIT DROP handles it if transaction ends
            await db.execute("DROP TABLE IF EXISTS promo_import_tmp")


async def get_promo_code(code: str, bot_id: int) -> Optional[Dict]:
    async with get_connection() as db:
        return await db.fetchrow("SELECT * FROM promo_codes WHERE code = $1 AND bot_id = $2", code, bot_id)


async def use_promo_code(code_id: int, user_id: int) -> bool:
    """Mark code as used and return True if successful"""
    async with get_connection() as db:
        result = await db.execute("""
            UPDATE promo_codes 
            SET status = 'used', user_id = $1, used_at = NOW() 
            WHERE id = $2 AND status = 'active'
        """, user_id, code_id)
        # Check if row was updated (result string usually 'UPDATE 1')
        return "UPDATE 1" in result


async def get_promo_stats(bot_id: int) -> Dict:
    async with get_connection() as db:
        return await db.fetchrow("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                COUNT(CASE WHEN status = 'used' THEN 1 END) as used
            FROM promo_codes WHERE bot_id = $1
        """, bot_id)


async def get_promo_codes_paginated(bot_id: int, limit: int = 50, offset: int = 0) -> List[Dict]:
    async with get_connection() as db:
        return await db.fetch("""
            SELECT p.*, u.username, u.full_name 
            FROM promo_codes p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.bot_id = $1
            ORDER BY p.id DESC
            LIMIT $2 OFFSET $3
        """, bot_id, limit, offset)
