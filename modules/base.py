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
    
    async def load_enabled_modules(self, bot_id: int):
        """Load enabled modules for a specific bot from database.
        
        Uses bots.enabled_modules as primary source, falls back to module_settings.
        """
        from database.db import get_connection
        
        async with get_connection() as db:
            # First try to get from bots.enabled_modules (new approach)
            bot = await db.fetchrow(
                "SELECT enabled_modules FROM bots WHERE id = $1", bot_id
            )
            
            if bot and bot['enabled_modules']:
                enabled = set(bot['enabled_modules'])
            else:
                # Fallback to module_settings table (legacy)
                rows = await db.fetch("""
                    SELECT module_name, is_enabled 
                    FROM module_settings 
                    WHERE bot_id = $1
                """, bot_id)
                
                enabled = set()
                for row in rows:
                    if row['is_enabled']:
                        enabled.add(row['module_name'])
                
                # If still no settings, use defaults
                if not rows:
                    for module in self.modules.values():
                        if module.default_enabled:
                            enabled.add(module.name)
            
            self._enabled_modules[bot_id] = enabled
            logger.info(f"Bot {bot_id}: enabled modules = {enabled}")
    
    def is_enabled(self, bot_id: int, module_name: str) -> bool:
        """Check if a module is enabled for a specific bot."""
        if bot_id not in self._enabled_modules:
            # Not loaded yet, assume default
            module = self.modules.get(module_name)
            return module.default_enabled if module else False
        return module_name in self._enabled_modules.get(bot_id, set())
    
    async def enable_module(self, bot_id: int, module_name: str) -> bool:
        """Enable a module for a bot."""
        module = self.modules.get(module_name)
        if not module:
            return False
        
        from database.db import get_connection
        
        async with get_connection() as db:
            await db.execute("""
                INSERT INTO module_settings (bot_id, module_name, is_enabled, settings)
                VALUES ($1, $2, TRUE, $3)
                ON CONFLICT (bot_id, module_name) 
                DO UPDATE SET is_enabled = TRUE
            """, bot_id, module_name, "{}")
        
        if bot_id not in self._enabled_modules:
            self._enabled_modules[bot_id] = set()
        self._enabled_modules[bot_id].add(module_name)
        
        await module.on_enable(bot_id)
        return True
    
    async def disable_module(self, bot_id: int, module_name: str) -> bool:
        """Disable a module for a bot."""
        module = self.modules.get(module_name)
        if not module:
            return False
        
        from database.db import get_connection
        
        async with get_connection() as db:
            await db.execute("""
                INSERT INTO module_settings (bot_id, module_name, is_enabled, settings)
                VALUES ($1, $2, FALSE, $3)
                ON CONFLICT (bot_id, module_name) 
                DO UPDATE SET is_enabled = FALSE
            """, bot_id, module_name, "{}")
        
        if bot_id in self._enabled_modules:
            self._enabled_modules[bot_id].discard(module_name)
        
        await module.on_disable(bot_id)
        return True
    
    async def get_module_settings(self, bot_id: int, module_name: str) -> Dict[str, Any]:
        """Get settings for a module for a specific bot."""
        from database.db import get_connection
        import json
        
        module = self.modules.get(module_name)
        defaults = module.default_settings if module else {}
        
        async with get_connection() as db:
            row = await db.fetchrow("""
                SELECT settings FROM module_settings 
                WHERE bot_id = $1 AND module_name = $2
            """, bot_id, module_name)
            
            if row and row['settings']:
                settings = json.loads(row['settings']) if isinstance(row['settings'], str) else row['settings']
                return {**defaults, **settings}
            
            return defaults
    
    async def set_module_settings(self, bot_id: int, module_name: str, settings: Dict[str, Any]):
        """Update settings for a module for a specific bot."""
        from database.db import get_connection
        import json
        
        async with get_connection() as db:
            await db.execute("""
                INSERT INTO module_settings (bot_id, module_name, is_enabled, settings)
                VALUES ($1, $2, TRUE, $3)
                ON CONFLICT (bot_id, module_name) 
                DO UPDATE SET settings = $3
            """, bot_id, module_name, json.dumps(settings))


# Global module loader instance
module_loader = ModuleLoader()
