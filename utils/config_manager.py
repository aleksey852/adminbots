"""
Config Manager - Dynamic settings from database
Allows changing promo texts, keywords, messages without restart
"""
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from database import get_connection
import config

logger = logging.getLogger(__name__)


class ConfigManager:
    _settings: Dict[int, Dict[str, str]] = {} # bot_id -> {key: value}
    _messages: Dict[int, Dict[str, str]] = {} # bot_id -> {key: text}
    _initialized = False

    async def load(self):
        """Load all settings and messages from DB"""
        try:
            async with get_connection() as db:
                # Load settings
                rows = await db.fetch("SELECT bot_id, key, value FROM settings")
                self._settings = {}
                for row in rows:
                    bot_id = row['bot_id']
                    if bot_id not in self._settings:
                        self._settings[bot_id] = {}
                    self._settings[bot_id][row['key']] = row['value']
                
                # Load messages
                rows = await db.fetch("SELECT bot_id, key, text FROM messages")
                self._messages = {}
                for row in rows:
                    bot_id = row['bot_id']
                    if bot_id not in self._messages:
                        self._messages[bot_id] = {}
                    self._messages[bot_id][row['key']] = row['text']
                
            self._initialized = True
            logger.info("Loaded settings and messages")
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")

    def get_setting(self, key: str, default: Any = None, bot_id: int = None) -> Any:
        """Get setting value"""
        if not self._initialized: return default
        if bot_id and bot_id in self._settings:
            return self._settings[bot_id].get(key, default)
        # Fallback to any bot or defaults? 
        # Ideally we should require bot_id. If None, return default.
        return default

    def get_message(self, key: str, default: str = "", bot_id: int = None) -> str:
        """Get message text"""
        if not self._initialized: return default
        if bot_id and bot_id in self._messages:
            return self._messages[bot_id].get(key, default)
        return default

    async def set_setting(self, key: str, value: str, bot_id: int):
        """Update setting in DB and cache"""
        async with get_connection() as db:
            await db.execute("""
                INSERT INTO settings (bot_id, key, value, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (bot_id, key) DO UPDATE SET value = $3, updated_at = NOW()
            """, bot_id, key, str(value))
        
        if bot_id not in self._settings:
            self._settings[bot_id] = {}
        self._settings[bot_id][key] = str(value)

    async def set_message(self, key: str, text: str, bot_id: int):
        """Update message in DB and cache"""
        async with get_connection() as db:
            await db.execute("""
                INSERT INTO messages (bot_id, key, text, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (bot_id, key) DO UPDATE SET text = $3, updated_at = NOW()
            """, bot_id, key, text)
        
        if bot_id not in self._messages:
            self._messages[bot_id] = {}
        self._messages[bot_id][key] = text

    async def get_all_settings(self, bot_id: int):
        """Get all settings for admin panel"""
        async with get_connection() as db:
            return await db.fetch("SELECT * FROM settings WHERE bot_id = $1 ORDER BY key", bot_id)

    async def get_all_messages(self, bot_id: int):
        """Get all messages for admin panel"""
        async with get_connection() as db:
            return await db.fetch("SELECT * FROM messages WHERE bot_id = $1 ORDER BY key", bot_id)


config_manager = ConfigManager()
