"""
Modules package - Modular bot architecture

Re-exports from core for backwards compatibility.
"""
from core.module_base import BotModule
from core.module_loader import ModuleLoader, module_loader

__all__ = ['BotModule', 'ModuleLoader', 'module_loader']
