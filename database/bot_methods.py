"""
Bot-specific database methods - Simplified and lightweight
Each bot has its own database, methods operate on current context
"""
import logging, json
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

def escape_like(text: str) -> str:
    """Escape special LIKE characters (%, _) in search queries"""
    if not text: return ""
    return str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

_current_bot_db: ContextVar = ContextVar('current_bot_db', default=None)

def set_current_bot_db(db): _current_bot_db.set(db)
def get_current_bot_db():
    if not (db := _current_bot_db.get()): raise RuntimeError("No bot database context set")
    return db

@asynccontextmanager
async def bot_db_context(bot_id: int):
    from database.bot_db import bot_db_manager
    if not (db := bot_db_manager.get(bot_id)): raise RuntimeError(f"Bot {bot_id} not registered")
    token = _current_bot_db.set(db)
    try: yield db
    finally: _current_bot_db.reset(token)

# === User Methods ===

async def add_user(tg_id: int, user: str, name: str, phone: str) -> int:
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("INSERT INTO users (telegram_id, username, full_name, phone) VALUES ($1, $2, $3, $4) ON CONFLICT (telegram_id) DO UPDATE SET username=EXCLUDED.username, full_name=EXCLUDED.full_name, phone=EXCLUDED.phone RETURNING id", tg_id, user, name, phone)

async def get_user(tg_id: int):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", tg_id)

async def get_user_by_id(user_id: int):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

async def get_user_with_stats(tg_id: int):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchrow("SELECT u.*, COUNT(r.id) FILTER (WHERE r.status='valid') as valid_receipts, COUNT(r.id) as total_receipts, SUM(r.tickets) FILTER (WHERE r.status='valid') as total_tickets FROM users u LEFT JOIN receipts r ON r.user_id = u.id WHERE u.telegram_id = $1 GROUP BY u.id", tg_id)

async def get_users_paginated(page: int = 1, per_page: int = 50):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT u.*, COALESCE(SUM(r.tickets), 0) as total_tickets, COUNT(r.id) as receipt_count FROM users u LEFT JOIN receipts r ON r.user_id = u.id AND r.status = 'valid' GROUP BY u.id ORDER BY u.registered_at DESC LIMIT $1 OFFSET $2", per_page, (page-1)*per_page)

async def search_users(q: str):
    escaped = escape_like(q)
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT * FROM users WHERE full_name ILIKE $1 OR phone ILIKE $1 OR username ILIKE $1 OR telegram_id::text LIKE $1 LIMIT 100", f"%{escaped}%")

async def block_user(user_id: int, blocked: bool = True):
    async with get_current_bot_db().get_connection() as conn:
        return "UPDATE 1" in await conn.execute("UPDATE users SET is_blocked = $1 WHERE id = $2", blocked, user_id)

async def update_username(tg_id: int, user: str):
    async with get_current_bot_db().get_connection() as conn:
        await conn.execute("UPDATE users SET username = $1 WHERE telegram_id = $2", user, tg_id)

async def block_user_by_telegram_id(tg_id: int):
    async with get_current_bot_db().get_connection() as conn:
        await conn.execute("UPDATE users SET is_blocked = TRUE WHERE telegram_id = $1", tg_id)

# === Receipt Methods ===

async def add_receipt(user_id: int, status: str, raw_qr: str = None, product_name: str = None, tickets: int = 1, data: Dict = None, fiscal_drive_number: str = None, fiscal_document_number: str = None, fiscal_sign: str = None, total_sum: int = 0):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("INSERT INTO receipts (user_id, status, raw_qr, product_name, tickets, data, fiscal_drive_number, fiscal_document_number, fiscal_sign, total_sum) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) ON CONFLICT (fiscal_drive_number, fiscal_document_number, fiscal_sign) DO NOTHING RETURNING id", user_id, status, raw_qr, product_name, tickets, json.dumps(data) if data else None, fiscal_drive_number, fiscal_document_number, fiscal_sign, total_sum)

async def is_receipt_exists(fn, fd, fs):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("SELECT EXISTS(SELECT 1 FROM receipts WHERE fiscal_drive_number=$1 AND fiscal_document_number=$2 AND fiscal_sign=$3)", fn, fd, fs)

async def get_user_receipts(uid, limit=50, offset=0):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT * FROM receipts WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3", uid, limit, offset)

async def get_user_receipts_count(uid):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM receipts WHERE user_id = $1 AND status = 'valid'", uid) or 0

async def get_user_tickets_count(uid):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("SELECT COALESCE(SUM(tickets), 0) FROM receipts WHERE user_id = $1 AND status = 'valid'", uid) or 0

# === Promo Code Methods ===

async def get_promo_code(code: str):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchrow("SELECT * FROM promo_codes WHERE UPPER(code) = UPPER($1)", code)

async def use_promo_code(cid: int, uid: int) -> bool:
    async with get_current_bot_db().get_connection() as conn:
        return "UPDATE 1" in await conn.execute("UPDATE promo_codes SET status = 'used', user_id = $1, used_at = NOW() WHERE id = $2 AND status = 'active'", uid, cid)

async def add_promo_codes(codes: List[str], tickets: int = 1) -> int:
    if not (recs := [(c.strip().upper(), tickets, 'active') for c in codes if c.strip()]): return 0
    async with get_current_bot_db().get_connection() as conn:
        await conn.executemany("INSERT INTO promo_codes (code, tickets, status) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING", recs)
    return len(recs)

# === Campaigns & Raffle ===

async def add_campaign(type: str, content: Dict, scheduled: datetime = None):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("INSERT INTO campaigns (type, content, scheduled_for) VALUES ($1, $2, $3) RETURNING id", type, json.dumps(content), scheduled)

async def get_pending_campaigns():
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT * FROM campaigns WHERE is_completed = FALSE AND (scheduled_for IS NULL OR scheduled_for <= NOW()) ORDER BY id")

async def mark_campaign_completed(cid: int, s: int = 0, f: int = 0):
    async with get_current_bot_db().get_connection() as conn:
        await conn.execute("UPDATE campaigns SET is_completed=TRUE, completed_at=NOW(), sent_count=$2, failed_count=$3 WHERE id=$1", cid, s, f)

async def add_winner(cid: int, uid: int, tg_id: int, prize: str):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("INSERT INTO winners (campaign_id, user_id, telegram_id, prize_name) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING RETURNING id", cid, uid, tg_id, prize)

async def get_raffle_participants():
    """Get participants with their total tickets for raffle selection"""
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("""
            SELECT u.id as user_id, u.telegram_id, u.full_name, u.username, 
                   SUM(s.t) as total_tickets 
            FROM users u 
            JOIN (
                SELECT user_id, tickets as t FROM receipts WHERE status='valid' 
                UNION ALL SELECT user_id, tickets FROM manual_tickets 
                UNION ALL SELECT user_id, tickets FROM promo_codes WHERE status='used'
            ) s ON u.id = s.user_id 
            WHERE u.is_blocked = FALSE 
            GROUP BY u.id 
            HAVING SUM(s.t) > 0
        """)

async def get_participants_count():
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM (SELECT user_id FROM receipts WHERE status='valid' UNION SELECT user_id FROM manual_tickets UNION SELECT user_id FROM promo_codes WHERE status='used') s")

async def get_total_tickets_count():
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("SELECT COALESCE(SUM(tickets), 0) FROM (SELECT tickets FROM receipts WHERE status='valid' UNION ALL SELECT tickets FROM manual_tickets UNION ALL SELECT tickets FROM promo_codes WHERE status='used') s") or 0

async def get_participants_with_tickets(): 
    return await get_raffle_participants()

async def select_random_winners_db(count: int, prize: str, exclude_user_ids: list = None):
    """
    Memory-efficient DB-side weighted random winner selection.
    Uses PostgreSQL random() with inverse weight for weighted selection.
    """
    exclude_ids = exclude_user_ids or []
    async with get_current_bot_db().get_connection() as conn:
        # Weighted random: users with more tickets have proportionally higher chance
        return await conn.fetch("""
            WITH eligible AS (
                SELECT u.id as user_id, u.telegram_id, u.full_name, u.username,
                       SUM(s.t) as total_tickets
                FROM users u
                JOIN (
                    SELECT user_id, tickets as t FROM receipts WHERE status='valid'
                    UNION ALL SELECT user_id, tickets FROM manual_tickets
                    UNION ALL SELECT user_id, tickets FROM promo_codes WHERE status='used'
                ) s ON u.id = s.user_id
                WHERE u.is_blocked = FALSE
                  AND u.id != ALL($3::int[])
                GROUP BY u.id
                HAVING SUM(s.t) > 0
            )
            SELECT user_id, telegram_id, full_name, username, total_tickets, $2 as prize_name
            FROM eligible
            ORDER BY -log(random()) / total_tickets  -- Weighted random using exponential distribution
            LIMIT $1
        """, count, prize, exclude_ids)

async def get_raffle_losers(cid: int):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT DISTINCT u.id, u.telegram_id FROM users u JOIN (SELECT user_id FROM receipts WHERE status='valid' UNION SELECT user_id FROM manual_tickets UNION SELECT user_id FROM promo_codes WHERE status='used') s ON u.id = s.user_id WHERE u.is_blocked = FALSE AND u.id NOT IN (SELECT user_id FROM winners WHERE campaign_id = $1)", cid)

async def get_raffle_losers_paginated(cid: int, last_id: int = 0, limit: int = 100):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT DISTINCT u.id, u.telegram_id FROM users u JOIN (SELECT user_id FROM receipts WHERE status='valid' UNION SELECT user_id FROM manual_tickets UNION SELECT user_id FROM promo_codes WHERE status='used') s ON u.id = s.user_id WHERE u.is_blocked = FALSE AND u.id NOT IN (SELECT user_id FROM winners WHERE campaign_id = $1) AND u.id > $2 ORDER BY u.id LIMIT $3", cid, last_id, limit)

async def mark_winner_notified(wid: int):
    async with get_current_bot_db().get_connection() as conn:
        await conn.execute("UPDATE winners SET notified = TRUE, notified_at = NOW() WHERE id = $1", wid)

# === Broadcast Progress ===

async def get_broadcast_progress(cid: int):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchrow("SELECT * FROM broadcast_progress WHERE campaign_id = $1", cid)

async def save_broadcast_progress(cid: int, last_uid: int, sent: int, failed: int):
    async with get_current_bot_db().get_connection() as conn:
        await conn.execute("INSERT INTO broadcast_progress (campaign_id, last_user_id, sent_count, failed_count, updated_at) VALUES ($1, $2, $3, $4, NOW()) ON CONFLICT (campaign_id) DO UPDATE SET last_user_id=$2, sent_count=$3, failed_count=$4, updated_at=NOW()", cid, last_uid, sent, failed)

async def delete_broadcast_progress(cid: int):
    async with get_current_bot_db().get_connection() as conn:
        await conn.execute("DELETE FROM broadcast_progress WHERE campaign_id = $1", cid)

async def get_user_ids_paginated(last_id: int = 0, limit: int = 100):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT id, telegram_id FROM users WHERE is_blocked = FALSE AND id > $1 ORDER BY id LIMIT $2", last_id, limit)

async def get_all_users_for_broadcast():
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT id, telegram_id FROM users WHERE is_blocked = FALSE ORDER BY id")

# === Stats & Helpers ===

async def get_stats() -> Dict:
    async with get_current_bot_db().get_connection() as conn:
        import config
        # Use timezone-aware 'now' then strip TZ for naive DB comparison if necessary
        # config.get_now() returns aware datetime
        t = config.get_now().replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
        
        u = await conn.fetchrow("SELECT COUNT(*) as total_users, COUNT(*) FILTER (WHERE registered_at >= $1) as users_today, COUNT(*) FILTER (WHERE is_blocked=TRUE) as blocked FROM users", t)
        r = await conn.fetchrow("SELECT COUNT(*) as total_receipts, COUNT(*) FILTER (WHERE status='valid') as valid_receipts, COUNT(*) FILTER (WHERE created_at >= $1) as receipts_today, COALESCE(SUM(tickets) FILTER (WHERE status='valid'), 0) as total_tickets, COUNT(DISTINCT user_id) FILTER (WHERE status='valid') as participants FROM receipts", t)
        return {**dict(u), **dict(r), "total_winners": await conn.fetchval("SELECT COUNT(*) FROM winners")}

async def get_user_detail(uid: int):
    async with get_current_bot_db().get_connection() as conn:
        u = dict(await conn.fetchrow("SELECT * FROM users WHERE id = $1", uid) or {})
        if not u: return None
        s = await conn.fetchrow("SELECT COUNT(*) as total_receipts, COUNT(CASE WHEN status='valid' THEN 1 END) as valid_receipts, COALESCE(SUM(CASE WHEN status='valid' THEN total_sum END), 0) as total_sum FROM receipts WHERE user_id = $1", uid)
        w = await conn.fetch("SELECT w.*, c.created_at as raffle_date FROM winners w JOIN campaigns c ON w.campaign_id = c.id WHERE w.user_id = $1 ORDER BY w.created_at DESC", uid)
        return {**u, **dict(s), "wins": w, "bot_id": get_current_bot_db().bot_id}

async def get_user_wins(uid: int):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT w.*, c.completed_at FROM winners w JOIN campaigns c ON w.campaign_id = c.id WHERE w.user_id = $1 ORDER BY w.created_at DESC", uid)

async def get_all_winners_for_export():
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT w.*, u.full_name, u.phone, u.username, c.created_at as raffle_date FROM winners w JOIN users u ON w.user_id = u.id JOIN campaigns c ON w.campaign_id = c.id ORDER BY w.created_at DESC")

# === Settings & Jobs ===

async def get_setting(k: str, d: str = None):
    async with get_current_bot_db().get_connection() as conn:
        v = await conn.fetchval("SELECT value FROM settings WHERE key = $1", k)
        return v if v is not None else d

async def set_setting(k: str, v: str):
    async with get_current_bot_db().get_connection() as conn:
        await conn.execute("INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (key) DO UPDATE SET value=$2, updated_at=NOW()", k, v)

async def get_message(k: str, d: str = ""):
    async with get_current_bot_db().get_connection() as conn:
        v = await conn.fetchval("SELECT text FROM messages WHERE key = $1", k)
        return v if v is not None else d

async def set_message(k: str, t: str):
    async with get_current_bot_db().get_connection() as conn:
        await conn.execute("INSERT INTO messages (key, text, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (key) DO UPDATE SET text=$2, updated_at=NOW()", k, t)

async def create_job(type: str, details: Dict = None):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("INSERT INTO jobs (type, status, details) VALUES ($1, 'pending', $2) RETURNING id", type, json.dumps(details or {}))

async def get_job(jid: int):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", jid)

async def update_job(jid: int, status: str = None, progress: int = None, details: Dict = None):
    async with get_current_bot_db().get_connection() as conn:
        fields, vals = [], []
        if status: fields.append(f"status = ${len(vals)+1}"); vals.append(status)
        if progress is not None: fields.append(f"progress = ${len(vals)+1}"); vals.append(progress)
        if details: fields.append(f"details = COALESCE(details, '{{}}'::jsonb) || ${len(vals)+1}"); vals.append(json.dumps(details))
        if fields: await conn.execute(f"UPDATE jobs SET {', '.join(fields)}, updated_at=NOW() WHERE id=${len(vals)+1}", *vals, jid)

# === Manual Tickets & Final Raffle ===

async def add_manual_tickets(uid: int, tix: int, reason: str = None, by: str = None):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("INSERT INTO manual_tickets (user_id, tickets, reason, created_by) VALUES ($1, $2, $3, $4) RETURNING id", uid, tix, reason, by)

async def get_user_manual_tickets(uid: int):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT * FROM manual_tickets WHERE user_id = $1 ORDER BY created_at DESC", uid)

async def get_user_total_tickets(uid: int):
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetchval("SELECT COALESCE((SELECT SUM(tickets) FROM receipts WHERE user_id=$1 AND status='valid'), 0) + COALESCE((SELECT SUM(tickets) FROM manual_tickets WHERE user_id=$1), 0) + COALESCE((SELECT SUM(tickets) FROM promo_codes WHERE user_id=$1 AND status='used'), 0)", uid)

async def get_user_tickets_breakdown(uid: int) -> dict:
    """Get detailed breakdown of user tickets by source"""
    async with get_current_bot_db().get_connection() as conn:
        row = await conn.fetchrow("""
            SELECT 
                COALESCE((SELECT SUM(tickets) FROM receipts WHERE user_id=$1 AND status='valid'), 0) as from_receipts,
                COALESCE((SELECT SUM(tickets) FROM promo_codes WHERE user_id=$1 AND status='used'), 0) as from_promo,
                COALESCE((SELECT SUM(tickets) FROM manual_tickets WHERE user_id=$1), 0) as from_manual
        """, uid)
        if row:
            return {
                'from_receipts': row['from_receipts'] or 0,
                'from_promo': row['from_promo'] or 0,
                'from_manual': row['from_manual'] or 0,
                'total': (row['from_receipts'] or 0) + (row['from_promo'] or 0) + (row['from_manual'] or 0)
            }
        return {'from_receipts': 0, 'from_promo': 0, 'from_manual': 0, 'total': 0}

async def get_all_tickets_for_final_raffle():
    async with get_current_bot_db().get_connection() as conn:
        return await conn.fetch("SELECT u.id as user_id, u.telegram_id, u.full_name, u.username, COALESCE(r.t, 0) + COALESCE(m.t, 0) + COALESCE(p.t, 0) as total_tickets FROM users u LEFT JOIN (SELECT user_id, SUM(tickets) as t FROM receipts WHERE status='valid' GROUP BY 1) r ON u.id = r.user_id LEFT JOIN (SELECT user_id, SUM(tickets) as t FROM manual_tickets GROUP BY 1) m ON u.id = m.user_id LEFT JOIN (SELECT user_id, SUM(tickets) as t FROM promo_codes WHERE status='used' GROUP BY 1) p ON u.id = p.user_id WHERE u.is_blocked = FALSE AND (r.t > 0 OR m.t > 0 OR p.t > 0)")

# === Utils & Legacy ===

# Whitelist of allowed fields for dynamic updates
ALLOWED_USER_FIELDS = {'full_name', 'phone', 'username', 'is_blocked'}

async def update_user_fields(uid: int, **kwargs):
    async with get_current_bot_db().get_connection() as conn:
        fields, vals = [], []
        for k, v in kwargs.items():
            if k not in ALLOWED_USER_FIELDS:
                logger.warning(f"Attempted to update non-whitelisted field: {k}")
                continue
            if v is not None: 
                fields.append(f"{k} = ${len(vals)+1}")
                vals.append(v)
        if fields: 
            await conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=${len(vals)+1}", *vals, uid)

async def get_user_receipts_detailed(uid, limit=50): return await get_user_receipts(uid, limit)
async def get_total_users_count():
    async with get_current_bot_db().get_connection() as conn: return await conn.fetchval("SELECT COUNT(*) FROM users") or 0
async def get_total_receipts_count():
    async with get_current_bot_db().get_connection() as conn: return await conn.fetchval("SELECT COUNT(*) FROM receipts") or 0
async def get_promo_stats():
    async with get_current_bot_db().get_connection() as conn:
        r = await conn.fetchrow("SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE status='used') as used, COUNT(*) FILTER (WHERE status='active') as active FROM promo_codes")
        return dict(r)
async def get_promo_codes_paginated(limit=50, offset=0, search_query: str = None):
    async with get_current_bot_db().get_connection() as conn:
        if search_query:
            q = escape_like(search_query)
            return await conn.fetch("SELECT pc.*, u.username, u.full_name FROM promo_codes pc LEFT JOIN users u ON pc.user_id = u.id WHERE pc.code ILIKE $1 OR u.username ILIKE $1 ORDER BY pc.created_at DESC LIMIT $2 OFFSET $3", f"%{q}%", limit, offset)
        return await conn.fetch("SELECT pc.*, u.username, u.full_name FROM promo_codes pc LEFT JOIN users u ON pc.user_id = u.id ORDER BY pc.created_at DESC LIMIT $1 OFFSET $2", limit, offset)
async def get_all_receipts_paginated(page=1, per_page=50):
    async with get_current_bot_db().get_connection() as conn: return await conn.fetch("SELECT r.*, u.full_name, u.username FROM receipts r JOIN users u ON r.user_id = u.id ORDER BY r.created_at DESC LIMIT $1 OFFSET $2", per_page, (page-1)*per_page)
async def get_recent_raffles_with_winners(limit=5):
    async with get_current_bot_db().get_connection() as conn:
        recs = [dict(r) for r in await conn.fetch("SELECT * FROM campaigns WHERE type='raffle' AND is_completed=TRUE ORDER BY completed_at DESC LIMIT $1", limit)]
        for r in recs:
            r['content'] = json.loads(r['content']) if isinstance(r['content'], str) else r['content']
            r['winners'] = await conn.fetch("SELECT w.*, u.full_name, u.username FROM winners w JOIN users u ON w.user_id = u.id WHERE w.campaign_id = $1", r['id'])
        return recs
async def get_stats_by_days(days=14):
    async with get_current_bot_db().get_connection() as conn: return await conn.fetch("WITH ds AS (SELECT generate_series(CURRENT_DATE-($1||' days')::interval,CURRENT_DATE,'1 day'::interval)::date AS d) SELECT ds.d as day, COALESCE(u.c,0) as users, COALESCE(r.c,0) as receipts FROM ds LEFT JOIN (SELECT DATE(registered_at) as d,COUNT(*) as c FROM users GROUP BY 1) u ON ds.d=u.d LEFT JOIN (SELECT DATE(created_at) as d,COUNT(*) as c FROM receipts WHERE status='valid' GROUP BY 1) r ON ds.d=r.d ORDER BY 1", str(days))
async def get_recent_campaigns(limit=20):
    async with get_current_bot_db().get_connection() as conn:
        recs = [dict(r) for r in await conn.fetch("SELECT * FROM campaigns ORDER BY created_at DESC LIMIT $1", limit)]
        for r in recs:
            if isinstance(r.get('content'), str):
                try: r['content'] = json.loads(r['content'])
                except: pass
        return recs
async def get_active_jobs():
    async with get_current_bot_db().get_connection() as conn: return await conn.fetch("SELECT * FROM jobs WHERE status IN ('pending', 'processing') ORDER BY created_at DESC")

# Missing legacy methods from __init__.py exports
async def get_all_settings():
    async with get_current_bot_db().get_connection() as conn: return await conn.fetch("SELECT * FROM settings ORDER BY key")
async def get_all_messages():
    async with get_current_bot_db().get_connection() as conn: return await conn.fetch("SELECT * FROM messages ORDER BY key")
async def save_winners_atomic(cid, winners):
    if not winners: return 0
    recs = [(cid, w['user_id'], w['telegram_id'], w['prize_name']) for w in winners]
    async with get_current_bot_db().get_connection() as conn:
        await conn.executemany("INSERT INTO winners (campaign_id, user_id, telegram_id, prize_name) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING", recs)
    return len(winners)
async def get_campaign_winners(cid):
    async with get_current_bot_db().get_connection() as conn: return await conn.fetch("SELECT * FROM winners WHERE campaign_id = $1", cid)
# Removed get_all_users_count (redundant alias)
