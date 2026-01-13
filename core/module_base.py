"""
Bot Module Base Class

This is the contract that all modules must implement.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from aiogram import Router
import logging
import os
import json

logger = logging.getLogger(__name__)

# Cache for bot manifests
_manifest_cache: Dict[int, Dict] = {}


def get_bot_manifest(bot_id: int) -> Dict:
    """Get cached manifest for a bot."""
    if bot_id in _manifest_cache:
        return _manifest_cache[bot_id]
    
    try:
        import asyncio
        from database.panel_db import get_bot_by_id
        
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return {}
        
        bot = loop.run_until_complete(get_bot_by_id(bot_id))
        if bot and bot.get('manifest_path'):
            manifest_file = os.path.join(bot['manifest_path'], 'manifest.json')
            if os.path.exists(manifest_file):
                with open(manifest_file, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                    _manifest_cache[bot_id] = manifest
                    return manifest
    except Exception as e:
        logger.debug(f"Could not load manifest for bot {bot_id}: {e}")
    
    return {}


def clear_manifest_cache(bot_id: int = None):
    """Clear manifest cache for a bot or all bots."""
    if bot_id:
        _manifest_cache.pop(bot_id, None)
    else:
        _manifest_cache.clear()


class BotModule(ABC):
    """
    Base class for all bot modules.
    
    Each module can be enabled/disabled per bot and configured via manifest.json
    or through the admin panel UI.
    
    Configuration hierarchy (highest priority first):
    1. Database overrides (via panel)
    2. manifest.json module_config
    3. Module default_settings
    
    Example manifest.json:
    {
        "modules": ["core", "promo"],
        "module_config": {
            "promo": {
                "max_codes_per_user": 3
            }
        }
    }
    """
    
    # === REQUIRED: Override in subclasses ===
    name: str = "base"
    version: str = "1.0.0"
    description: str = "Base module"
    
    # === OPTIONAL: Override as needed ===
    default_enabled: bool = True
    dependencies: List[str] = []
    default_settings: Dict[str, Any] = {}
    default_messages: Dict[str, str] = {}
    
    # Menu buttons for Core module to include in main menu
    # Format: [{"text": "🔑 Ввести код", "order": 10}]
    # order: lower = higher in menu
    menu_buttons: List[Dict[str, Any]] = []
    
    # === STATE PROTECTION ===
    # Timeout in seconds before auto-clearing user state (prevents "stuck" users)
    state_timeout: int = 600  # 10 minutes
    
    # States this module uses (for documentation and monitoring)
    # Format: ["waiting_code", "editing_name"]
    states: List[str] = []
    
    # Settings schema for admin panel UI
    # Format: { "key": { "type": "text|checkbox|number|textarea|select", "label": "...", "default": ... } }
    settings_schema: Dict[str, Dict[str, Any]] = {}
    
    def __init__(self):
        self.router = Router(name=self.name)
        self._setup_handlers()
    
    @abstractmethod
    def _setup_handlers(self):
        """Setup aiogram handlers for this module. Override in subclasses."""
        pass
    
    # === LIFECYCLE HOOKS ===
    
    async def on_enable(self, bot_id: int):
        """Called when module is enabled for a bot."""
        logger.info(f"Module '{self.name}' enabled for bot {bot_id}")
    
    async def on_disable(self, bot_id: int):
        """Called when module is disabled for a bot."""
        logger.info(f"Module '{self.name}' disabled for bot {bot_id}")
    
    async def on_bot_start(self, bot_id: int):
        """Called when a bot starts. Use for initialization."""
        pass
    
    async def on_bot_stop(self, bot_id: int):
        """Called when a bot stops. Use for cleanup."""
        pass
    
    # === CONFIGURATION ===
    
    def get_router(self) -> Router:
        """Get the aiogram Router for this module."""
        return self.router
    
    def get_config(self, bot_id: int, key: str, default: Any = None) -> Any:
        """
        Get a configuration value for this module.
        
        Reads from manifest.json's module_config section.
        Falls back to default_settings, then to provided default.
        """
        manifest = get_bot_manifest(bot_id)
        module_config = manifest.get('module_config', {}).get(self.name, {})
        
        if key in module_config:
            return module_config[key]
        
        if key in self.default_settings:
            return self.default_settings[key]
        
        return default
    
    def get_all_config(self, bot_id: int) -> Dict[str, Any]:
        """Get all configuration for this module."""
        config = self.default_settings.copy()
        manifest = get_bot_manifest(bot_id)
        module_config = manifest.get('module_config', {}).get(self.name, {})
        config.update(module_config)
        return config
    
    async def get_settings(self, bot_id: int) -> Dict[str, Any]:
        """
        Get effective settings for this module and bot.
        Merges: default_settings < manifest config < database overrides
        """
        from database.panel_db import get_module_settings
        
        settings = self.default_settings.copy()
        
        manifest = get_bot_manifest(bot_id)
        module_config = manifest.get('module_config', {}).get(self.name, {})
        settings.update(module_config)
        
        db_settings = await get_module_settings(bot_id, self.name)
        settings.update(db_settings)
        
        return settings
    
    async def save_settings(self, bot_id: int, settings: Dict[str, Any]):
        """Save settings for this module and bot."""
        from database.panel_db import set_module_settings
        await set_module_settings(bot_id, self.name, settings)
    
    # === INTROSPECTION ===
    
    def get_handlers(self) -> List[str]:
        """Get names of all handlers registered in this module's router."""
        handlers = []
        for observer in self.router.observers.values():
            for handler in observer.handlers:
                callback = handler.callback
                if hasattr(callback, '__name__'):
                    handlers.append(callback.__name__)
                elif hasattr(callback, 'func') and hasattr(callback.func, '__name__'):
                    handlers.append(callback.func.__name__)
        return handlers
    
    # === DATABASE (Optional Override) ===
    
    def get_migrations(self) -> List[str]:
        """
        Return SQL migration statements for this module's tables.
        Override in subclasses that need database tables.
        """
        return []
    
    # === ADMIN PANEL API (Optional Override) ===
    
    def get_api_router(self) -> Optional[Router]:
        """
        Return FastAPI router for admin panel.
        Override in subclasses that need custom API endpoints.
        """
        return None
    
    # === MONITORING & STATUS (Optional Override) ===
    
    async def get_status(self, bot_id: int) -> Dict[str, Any]:
        """
        Return current status of this module for monitoring dashboards.
        
        Override to provide module-specific metrics like:
        - Active tasks count
        - Pending items
        - Last activity timestamp
        
        Example override:
            async def get_status(self, bot_id: int):
                return {
                    **await super().get_status(bot_id),
                    "pending_receipts": await self.get_pending_count(bot_id),
                    "last_processed": self.last_processed_at
                }
        """
        return {
            "module": self.name,
            "version": self.version,
            "enabled": True,
            "tasks": [],  # Override to add active tasks
            "metrics": {}  # Override to add custom metrics
        }
    
    async def get_health(self, bot_id: int) -> Dict[str, Any]:
        """
        Return health check status for this module.
        
        Override to check module-specific dependencies like:
        - External API availability
        - Database connection
        - Required services
        
        Returns:
            {"healthy": bool, "issues": List[str]}
        """
        return {
            "healthy": True,
            "issues": []
        }
