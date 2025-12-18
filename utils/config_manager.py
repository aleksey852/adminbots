"""
Config Manager - Dynamic settings from database
Allows changing promo texts, keywords, messages without restart
"""
import logging
from typing import Dict, Any, Optional, List
from database import bot_methods
import config

logger = logging.getLogger(__name__)


class ConfigManager:
    _settings: Dict[int, Dict[str, str]] = {}  # bot_id -> {key: value}
    _messages: Dict[int, Dict[str, str]] = {}  # bot_id -> {key: text}
    _initialized = False

    async def load(self):
        """Load settings - now a no-op since we fetch from context per-request"""
        self._initialized = True
        logger.info("ConfigManager initialized")

    def get_setting(self, key: str, default: Any = None, bot_id: int = None) -> Any:
        """Get setting value from cache"""
        if not self._initialized:
            return default
        if bot_id and bot_id in self._settings:
            return self._settings[bot_id].get(key, default)
        return default

    def get_message(self, key: str, default: str = "", bot_id: int = None) -> str:
        """Get message text from cache"""
        if not self._initialized:
            return default
        if bot_id and bot_id in self._messages:
            return self._messages[bot_id].get(key, default)
        return default

    async def set_setting(self, key: str, value: str, bot_id: int):
        """Update setting in DB and cache (uses current bot context)"""
        db = bot_methods.get_current_bot_db()
        async with db.get_connection() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()
            """, key, str(value))
        
        if bot_id not in self._settings:
            self._settings[bot_id] = {}
        self._settings[bot_id][key] = str(value)

    async def set_message(self, key: str, text: str, bot_id: int):
        """Update message in DB and cache (uses current bot context)"""
        db = bot_methods.get_current_bot_db()
        async with db.get_connection() as conn:
            await conn.execute("""
                INSERT INTO messages (key, text, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO UPDATE SET text = $2, updated_at = NOW()
            """, key, text)
        
        if bot_id not in self._messages:
            self._messages[bot_id] = {}
        self._messages[bot_id][key] = text

    async def get_all_settings(self, bot_id: int) -> List[Dict]:
        """Get all settings for admin panel (uses current bot context)"""
        db = bot_methods.get_current_bot_db()
        async with db.get_connection() as conn:
            return await conn.fetch("SELECT * FROM settings ORDER BY key")

    async def get_all_messages(self, bot_id: int) -> List[Dict]:
        """Get all messages for admin panel (uses current bot context)"""
        db = bot_methods.get_current_bot_db()
        async with db.get_connection() as conn:
            return await conn.fetch("SELECT * FROM messages ORDER BY key")

    async def load_for_bot(self, bot_id: int):
        """Load settings and messages for a specific bot into cache"""
        try:
            db = bot_methods.get_current_bot_db()
            async with db.get_connection() as conn:
                # Load settings
                rows = await conn.fetch("SELECT key, value FROM settings")
                self._settings[bot_id] = {row['key']: row['value'] for row in rows}
                
                # Load messages
                rows = await conn.fetch("SELECT key, text FROM messages")
                self._messages[bot_id] = {row['key']: row['text'] for row in rows}
            
            logger.debug(f"Loaded {len(self._settings.get(bot_id, {}))} settings for bot {bot_id}")
        except Exception as e:
            logger.error(f"Failed to load settings for bot {bot_id}: {e}")


config_manager = ConfigManager()
