"""
System Configuration

Only system-level settings that apply globally.
Bot-specific settings are stored in the database.
"""
import os
import logging
from dotenv import load_dotenv
from datetime import datetime
from typing import List
import pytz

logger = logging.getLogger(__name__)

load_dotenv()


# === Database ===
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://adminbots:password@localhost:5432/admin_bots")
PANEL_DATABASE_URL = os.getenv("PANEL_DATABASE_URL", DATABASE_URL)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "5"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "20"))

# === External APIs ===
PROVERKA_CHEKA_TOKEN = os.getenv("PROVERKA_CHEKA_TOKEN", "")
PROVERKA_CHEKA_URL = "https://proverkacheka.com/api/v1/check/get"

# === Admin Panel Auth ===
ADMIN_PANEL_USER = os.getenv("ADMIN_PANEL_USER", "admin")
ADMIN_PANEL_PASSWORD = os.getenv("ADMIN_PANEL_PASSWORD", "")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "")

# === System Limits ===
BROADCAST_BATCH_SIZE = int(os.getenv("BROADCAST_BATCH_SIZE", "25"))
MESSAGE_DELAY_SECONDS = float(os.getenv("MESSAGE_DELAY_SECONDS", "0.05"))
SCHEDULER_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL", "30"))
STATS_CACHE_TTL = int(os.getenv("STATS_CACHE_TTL", "60"))

# === Monitoring ===
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"
METRICS_PORT = int(os.getenv("METRICS_PORT", "9090"))

# === Timezone ===
TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Europe/Moscow"))


def get_now() -> datetime:
    """Get current time in configured timezone."""
    return datetime.now(TIMEZONE)


def validate_config() -> List[str]:
    """Validate critical settings on startup. Returns list of errors."""
    errors = []
    
    if not ADMIN_PANEL_PASSWORD:
        errors.append("ADMIN_PANEL_PASSWORD must be set")
    if not ADMIN_SECRET_KEY:
        errors.append("ADMIN_SECRET_KEY must be set")
    
    # Warnings (non-blocking)
    if not PROVERKA_CHEKA_TOKEN:
        print("⚠️  WARNING: PROVERKA_CHEKA_TOKEN is not set. Receipt checking will fail.")
    
    return errors
