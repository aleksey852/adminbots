"""
Admin Bots Platform - Centralized Configuration
Simplified: removed runtime validation, consolidated helpers
"""
import os
import logging
from dotenv import load_dotenv
from datetime import datetime
from typing import List, Optional
import pytz

logger = logging.getLogger(__name__)

load_dotenv()

# === Core ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
def _parse_admin_ids(env_val: str) -> List[int]:
    if not env_val: return []
    return [int(x.strip()) for x in env_val.split(",") if x.strip().isdigit()]

ADMIN_IDS: List[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Europe/Moscow"))

# === Database & Redis ===
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://adminbots:password@localhost:5432/admin_bots")
PANEL_DATABASE_URL = os.getenv("PANEL_DATABASE_URL", DATABASE_URL)  # Panel registry DB (can be same or separate)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DB_POOL_MIN, DB_POOL_MAX = int(os.getenv("DB_POOL_MIN", "5")), int(os.getenv("DB_POOL_MAX", "20"))

# === External API ===
PROVERKA_CHEKA_TOKEN = os.getenv("PROVERKA_CHEKA_TOKEN", "")
PROVERKA_CHEKA_URL = "https://proverkacheka.com/api/v1/check/get"

# === Promo Settings ===
TARGET_KEYWORDS = [x.strip().lower() for x in os.getenv("TARGET_KEYWORDS", "чипсы,buster,vibe").split(",")]
EXCLUDED_KEYWORDS = [x.strip().lower() for x in os.getenv("EXCLUDED_KEYWORDS", "mosk").split(",")]
PROMO_NAME = os.getenv("PROMO_NAME", "Admin Bots")
PROMO_START_DATE = os.getenv("PROMO_START_DATE", "2025-01-15")
PROMO_END_DATE = os.getenv("PROMO_END_DATE", "2025-03-15")
PROMO_PRIZES = os.getenv("PROMO_PRIZES", "iPhone 16, PlayStation 5, сертификаты")

# === Support ===
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@example.com")
SUPPORT_TELEGRAM = os.getenv("SUPPORT_TELEGRAM", "@YourSupportBot")

# === Limits & Timing ===
RECEIPTS_RATE_LIMIT = int(os.getenv("RECEIPTS_RATE_LIMIT", "50"))
RECEIPTS_DAILY_LIMIT = int(os.getenv("RECEIPTS_DAILY_LIMIT", "200"))
SCHEDULER_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL", "30"))
BROADCAST_BATCH_SIZE = int(os.getenv("BROADCAST_BATCH_SIZE", "25"))
MESSAGE_DELAY_SECONDS = float(os.getenv("MESSAGE_DELAY_SECONDS", "0.05"))
STATS_CACHE_TTL = int(os.getenv("STATS_CACHE_TTL", "60"))

# === Admin Panel ===
ADMIN_PANEL_USER = os.getenv("ADMIN_PANEL_USER", "admin")
ADMIN_PANEL_PASSWORD = os.getenv("ADMIN_PANEL_PASSWORD", "")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "")

# === Monitoring ===
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"
METRICS_PORT = int(os.getenv("METRICS_PORT", "9090"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def get_now() -> datetime:
    return datetime.now(TIMEZONE)


def parse_scheduled_time(time_str: str) -> Optional[datetime]:
    if not time_str:
        return None
    try:
        # Handle both space (manual) and T (datetime-local) separators
        clean_str = time_str.replace("T", " ")
        dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M")
        # Return naive datetime as DB expects TIMESTAMP without timezone
        return dt
    except Exception:
        return None


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_IDS


def is_promo_active() -> bool:
    try:
        now = get_now().replace(tzinfo=None) # Compare naive
        start = datetime.strptime(PROMO_START_DATE, "%Y-%m-%d")
        end = datetime.strptime(PROMO_END_DATE, "%Y-%m-%d")
        return start <= now <= end
    except Exception as e:
        logger.error(f"Error checking promo status: {e}")
        return True


def days_until_end() -> int:
    try:
        now = get_now().replace(tzinfo=None)
        end = datetime.strptime(PROMO_END_DATE, "%Y-%m-%d")
        return max(0, (end - now).days)
    except Exception as e:
        logger.error(f"Error calculating days until end: {e}")
        return 0


def validate_config() -> List[str]:
    """Validate critical settings on startup"""
    errors = []
    # Relaxed validation for zero-config deployment
    if not BOT_TOKEN:
        print("⚠️  WARNING: BOT_TOKEN is not set in .env. Bots will not poll until configured.")
    if not PROVERKA_CHEKA_TOKEN:
        print("⚠️  WARNING: PROVERKA_CHEKA_TOKEN is not set. Receipt checking will fail.")
    if not ADMIN_IDS:
        print("⚠️  WARNING: ADMIN_IDS is not set. No telegram admins configured.")
        
    # Relaxed password/secret requirements for internal project
    if not ADMIN_PANEL_PASSWORD:
        errors.append("ADMIN_PANEL_PASSWORD must be set")
    if not ADMIN_SECRET_KEY:
        errors.append("ADMIN_SECRET_KEY must be set")
    return errors
