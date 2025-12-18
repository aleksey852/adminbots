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


# Global module loader instance
module_loader = ModuleLoader()
