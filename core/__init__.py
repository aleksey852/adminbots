"""
Admin Bots Framework — Core

This package contains the framework core that modules build upon.
Do not modify these files for bot-specific logic.
"""

from .module_base import BotModule
from .module_loader import ModuleLoader, module_loader
from .event_bus import EventBus, event_bus

__all__ = [
    "BotModule",
    "ModuleLoader", 
    "module_loader",
    "EventBus",
    "event_bus",
]
