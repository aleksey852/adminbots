"""
Bot Modules Framework
Base classes for modular bot architecture

Modules are reusable components that bots can include via manifest.json.
Configuration is read from manifest.json's module_config section.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable
from aiogram import Router
import logging
import os
import json

logger = logging.getLogger(__name__)

# Cache for bot manifests
_manifest_cache: Dict[int, Dict] = {}


def get_bot_manifest(bot_id: int) -> Dict:
    """Get cached manifest for a bot"""
    if bot_id in _manifest_cache:
        return _manifest_cache[bot_id]
    
    # Try to load from database
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
    """Clear manifest cache for a bot or all bots"""
    if bot_id:
        _manifest_cache.pop(bot_id, None)
    else:
        _manifest_cache.clear()


class BotModule(ABC):
    """
    Base class for all bot modules.
    
    Each module can be enabled/disabled per bot and configured via manifest.json.
    
    Configuration hierarchy (highest priority first):
    1. Database overrides (via panel)
    2. manifest.json module_config
    3. Module default_settings
    
    Example manifest.json:
    {
        "modules": ["core", "promo"],
        "module_config": {
            "promo": {
                "max_codes_per_user": 3,
                "notify_admin": true
            }
        }
    }
    """
    
    # Module metadata - override in subclasses
    name: str = "base"
    version: str = "1.0.0"
    description: str = "Base module"
    default_enabled: bool = True
    
    # Dependencies on other modules (by name)
    dependencies: List[str] = []
    
    # Default settings for this module
    default_settings: Dict[str, Any] = {}
    
    # Default messages for this module
    default_messages: Dict[str, str] = {}

    # Settings schema for admin panel
    # Format: { "key": { "type": "text|checkbox|number|textarea", "label": "Label", "default": "val", "required": True } }
    settings_schema: Dict[str, Dict[str, Any]] = {}
    
    def __init__(self):
        self.router = Router(name=self.name)
        self._setup_handlers()
    
    @abstractmethod
    def _setup_handlers(self):
        """Setup aiogram handlers for this module. Override in subclasses."""
        pass
    
    async def on_enable(self, bot_id: int):
        """Called when module is enabled for a bot. Override for custom logic."""
        logger.info(f"Module '{self.name}' enabled for bot {bot_id}")
    
    async def on_disable(self, bot_id: int):
        """Called when module is disabled for a bot. Override for custom logic."""
        logger.info(f"Module '{self.name}' disabled for bot {bot_id}")
    
    def get_router(self) -> Router:
        """Get the aiogram Router for this module."""
        return self.router

    def get_config(self, bot_id: int, key: str, default: Any = None) -> Any:
        """
        Get a configuration value for this module.
        
        Reads from manifest.json's module_config section.
        Falls back to default_settings, then to provided default.
        
        Args:
            bot_id: Bot database ID
            key: Configuration key
            default: Default value if not found
        
        Returns:
            Configuration value
        
        Example:
            max_codes = self.get_config(bot_id, 'max_codes_per_user', 1)
        """
        # Try manifest first
        manifest = get_bot_manifest(bot_id)
        module_config = manifest.get('module_config', {}).get(self.name, {})
        
        if key in module_config:
            return module_config[key]
        
        # Fall back to default_settings
        if key in self.default_settings:
            return self.default_settings[key]
        
        return default
    
    def get_all_config(self, bot_id: int) -> Dict[str, Any]:
        """
        Get all configuration for this module.
        
        Merges default_settings with manifest config.
        """
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
        
        # Start with defaults
        settings = self.default_settings.copy()
        
        # Layer manifest config
        manifest = get_bot_manifest(bot_id)
        module_config = manifest.get('module_config', {}).get(self.name, {})
        settings.update(module_config)
        
        # Layer database overrides (highest priority)
        db_settings = await get_module_settings(bot_id, self.name)
        settings.update(db_settings)
        
        return settings

    async def save_settings(self, bot_id: int, settings: Dict[str, Any]):
        """Save settings for this module and bot."""
        from database.panel_db import set_module_settings
        await set_module_settings(bot_id, self.name, settings)

    def get_handlers(self) -> List[str]:
        """Get names of all handlers registered in this module's router."""
        handlers = []
        for observer in self.router.observers.values():
            for handler in observer.handlers:
                # Try to get handler name from callback
                callback = handler.callback
                if hasattr(callback, '__name__'):
                    handlers.append(callback.__name__)
                elif hasattr(callback, 'func') and hasattr(callback.func, '__name__'):
                    handlers.append(callback.func.__name__)
        return handlers


class ModuleLoader:
    """
    Manages loading and registering bot modules.
    
    Module enable/disable is managed through panel_db (bot_registry.enabled_modules)
    and enforced in BotMiddleware. This class handles module registration and lookup.
    """
    
    def __init__(self):
        self.modules: Dict[str, BotModule] = {}
        self._enabled_modules: Dict[int, set] = {}  # bot_id -> set of module names
    
    def register(self, module: BotModule):
        """Register a module."""
        if module.name in self.modules:
            logger.warning(f"Module '{module.name}' already registered, replacing...")
        self.modules[module.name] = module
        logger.info(f"Registered module: {module.name} v{module.version}")
    
    def get_module(self, name: str) -> Optional[BotModule]:
        """Get a registered module by name."""
        return self.modules.get(name)
    
    def get_all_modules(self) -> List[BotModule]:
        """Get all registered modules."""
        return list(self.modules.values())
    
    def get_module_by_handler(self, handler_name: str) -> Optional[BotModule]:
        """Find which module contains a handler with the given name."""
        for module in self.modules.values():
            if handler_name in module.get_handlers():
                return module
        return None
    
    def set_enabled_modules(self, bot_id: int, module_names: set):
        """Set enabled modules for a bot (called from middleware)."""
        self._enabled_modules[bot_id] = module_names
    
    def is_enabled(self, bot_id: int, module_name: str) -> bool:
        """Check if a module is enabled for a specific bot."""
        if bot_id not in self._enabled_modules:
            # Not loaded yet, assume default
            module = self.modules.get(module_name)
            return module.default_enabled if module else False
        return module_name in self._enabled_modules.get(bot_id, set())
    
    def get_default_enabled_modules(self) -> set:
        """Get set of module names that are enabled by default."""
        return {m.name for m in self.modules.values() if m.default_enabled}

    def discover_modules(self, package_path: str = "modules"):
        """
        Automatically discover and register modules in the given package path.
        """
        import importlib
        import os
        import inspect
        import pkgutil

        # Assume package_path is relative to project root
        project_root = os.getcwd()
        full_path = os.path.join(project_root, package_path)
        
        if not os.path.exists(full_path):
            logger.error(f"Module path not found: {full_path}")
            return

        logger.info(f"Discovering modules in {package_path}...")

        # Helper to process a module object
        def register_from_module(mod):
            try:
                found = False
                for name, obj in inspect.getmembers(mod):
                    # We look for INSTANTIATED BotModules (like core_module = CoreModule())
                    # to avoid re-instantiation issues if they need params.
                    if isinstance(obj, BotModule) and obj.__class__ != BotModule:
                        self.register(obj)
                        found = True
                if not found:
                    # Optional: Look for classes? For now strict to instances to match current pattern.
                    pass
            except Exception as e:
                logger.error(f"Error scanning module {mod}: {e}")

        # Scan directory
        for item in os.listdir(full_path):
            # Skip hidden files, __init__, base
            if item.startswith('.') or item == "__init__.py" or item == "base.py":
                continue

            module_name = None
            
            # Case 1: Subdirectory (package) like 'modules/core'
            if os.path.isdir(os.path.join(full_path, item)):
                 if os.path.exists(os.path.join(full_path, item, "__init__.py")):
                     module_name = f"{package_path}.{item}"
            
            # Case 2: Single file like 'modules/subscription.py'
            elif item.endswith(".py"):
                 module_name = f"{package_path}.{item[:-3]}"

            if module_name:
                try:
                    mod = importlib.import_module(module_name)
                    register_from_module(mod)
                except Exception as e:
                    logger.error(f"Failed to import module {module_name}: {e}")


# Global module loader instance
module_loader = ModuleLoader()
