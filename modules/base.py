"""
Bot Modules Framework
Base classes for modular bot architecture
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from aiogram import Router
import logging

logger = logging.getLogger(__name__)


class BotModule(ABC):
    """
    Base class for all bot modules.
    
    Each module can be enabled/disabled per bot and has its own settings.
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

    async def get_settings(self, bot_id: int) -> Dict[str, Any]:
        """
        Get effective settings for this module and bot.
        Merges default_settings with database overrides.
        """
        from database.panel_db import get_module_settings
        db_settings = await get_module_settings(bot_id, self.name)
        
        # Merge: start with defaults, override with DB
        settings = self.default_settings.copy()
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
            # Skip hidden files, __init__, base, and workflow (utility)
            if item.startswith('.') or item == "__init__.py" or item == "base.py" or item == "workflow.py":
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
