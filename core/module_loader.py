"""
Module Loader

Handles auto-discovery and registration of bot modules.
"""
import importlib
import inspect
import logging
import os
from typing import Dict, List, Optional

from .module_base import BotModule

logger = logging.getLogger(__name__)


class ModuleLoader:
    """
    Manages loading and registering bot modules.
    
    Features:
    - Auto-discovery of modules in the modules/ directory
    - Dependency resolution and ordered loading
    - Enable/disable per bot
    """
    
    def __init__(self):
        self.modules: Dict[str, BotModule] = {}
        self._enabled_modules: Dict[int, set] = {}  # bot_id -> set of module names
    
    def register(self, module: BotModule):
        """Register a module instance."""
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
    
    def get_modules_for_bot(self, bot_id: int) -> List[BotModule]:
        """Get modules enabled for a specific bot."""
        enabled = self._enabled_modules.get(bot_id, set())
        return [m for m in self.modules.values() if m.name in enabled]
    
    def set_enabled_modules(self, bot_id: int, module_names: set):
        """Set enabled modules for a bot (called from middleware)."""
        self._enabled_modules[bot_id] = module_names
    
    def is_enabled(self, bot_id: int, module_name: str) -> bool:
        """Check if a module is enabled for a specific bot."""
        if bot_id not in self._enabled_modules:
            module = self.modules.get(module_name)
            return module.default_enabled if module else False
        return module_name in self._enabled_modules.get(bot_id, set())
    
    def get_default_enabled_modules(self) -> set:
        """Get set of module names that are enabled by default."""
        return {m.name for m in self.modules.values() if m.default_enabled}
    
    def discover_modules(self, package_path: str = "modules"):
        """
        Auto-discover and register modules in the given package path.
        
        Scans for:
        - Subdirectories with __init__.py (package modules)
        - Standalone .py files (single-file modules)
        
        Looks for BotModule instances to register.
        """
        project_root = os.getcwd()
        full_path = os.path.join(project_root, package_path)
        
        if not os.path.exists(full_path):
            logger.error(f"Module path not found: {full_path}")
            return
        
        logger.info(f"Discovering modules in {package_path}...")
        
        def register_from_module(mod):
            """Find and register BotModule instances in a module."""
            try:
                for name, obj in inspect.getmembers(mod):
                    if isinstance(obj, BotModule) and obj.__class__ != BotModule:
                        self.register(obj)
            except Exception as e:
                logger.error(f"Error scanning module {mod}: {e}")
        
        # Scan directory
        for item in os.listdir(full_path):
            if item.startswith('.') or item == "__init__.py" or item == "base.py":
                continue
            
            # Skip template directory
            if item.startswith('_'):
                continue
            
            module_name = None
            item_path = os.path.join(full_path, item)
            
            # Package module (directory with __init__.py)
            if os.path.isdir(item_path):
                if os.path.exists(os.path.join(item_path, "__init__.py")):
                    module_name = f"{package_path}.{item}"
            
            # Single-file module
            elif item.endswith(".py"):
                module_name = f"{package_path}.{item[:-3]}"
            
            if module_name:
                try:
                    mod = importlib.import_module(module_name)
                    register_from_module(mod)
                except Exception as e:
                    logger.error(f"Failed to import module {module_name}: {e}")
    
    def resolve_dependencies(self) -> List[str]:
        """
        Return module names in dependency order.
        Raises ValueError if circular dependencies detected.
        """
        resolved = []
        seen = set()
        
        def resolve(name: str, path: List[str] = None):
            if path is None:
                path = []
            
            if name in path:
                raise ValueError(f"Circular dependency: {' -> '.join(path + [name])}")
            
            if name in seen:
                return
            
            module = self.modules.get(name)
            if not module:
                logger.warning(f"Unknown module in dependencies: {name}")
                return
            
            for dep in module.dependencies:
                resolve(dep, path + [name])
            
            seen.add(name)
            resolved.append(name)
        
        for name in self.modules:
            resolve(name)
        
        return resolved


# Global singleton
module_loader = ModuleLoader()
