"""
Bot Middleware - Injects bot_id, enabled modules and admin status into handlers
Sets database context for bot_methods
"""
from typing import Callable, Dict, Any, Awaitable, Set
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from bot_manager import bot_manager
from database.bot_db import bot_db_manager
from database import bot_methods
import logging

logger = logging.getLogger(__name__)

# Cache for enabled modules per bot (refreshed periodically)
_enabled_modules_cache: Dict[int, Set[str]] = {}


async def get_enabled_modules(bot_id: int) -> Set[str]:
    """Get enabled modules for a bot, with caching."""
    if bot_id in _enabled_modules_cache:
        return _enabled_modules_cache[bot_id]
    
    # Get from panel registry
    from database.panel_db import get_bot_by_id
    bot_info = await get_bot_by_id(bot_id)
    if bot_info and bot_info.get('enabled_modules'):
        modules = bot_info['enabled_modules']
    else:
        # Default modules - all existing modules
        modules = ['core', 'registration', 'receipts', 'promo', 'admin']
    
    _enabled_modules_cache[bot_id] = set(modules)
    return _enabled_modules_cache[bot_id]


def clear_modules_cache(bot_id: int = None):
    """Clear modules cache. Call when modules are updated."""
    if bot_id:
        _enabled_modules_cache.pop(bot_id, None)
    else:
        _enabled_modules_cache.clear()


def is_module_enabled_sync(bot_id: int, module_name: str) -> bool:
    """Synchronous check if module is enabled (from cache only)."""
    if bot_id not in _enabled_modules_cache:
        # Not loaded yet, assume enabled
        return True
    return module_name in _enabled_modules_cache.get(bot_id, set())


class BotMiddleware(BaseMiddleware):
    """
    Main middleware that injects:
    - bot_id: database bot ID
    - enabled_modules: set of enabled module names
    - is_admin: whether user is admin for this bot
    Also sets bot_methods database context for handler DB operations.
    """
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        bot = data.get("bot")
        if not bot:
            return await handler(event, data)

        bot_id = bot_manager.get_db_id(bot.id)
        if not bot_id:
            return await handler(event, data)
        
        data["bot_id"] = bot_id
        
        # Set database context for bot_methods with token for cleanup
        bot_db = bot_db_manager.get(bot_id)
        context_token = None
        if bot_db:
            # Get the ContextVar directly for token-based management
            from database.bot_methods import _current_bot_db
            context_token = _current_bot_db.set(bot_db)
        
        try:
            # Load enabled modules for this bot
            enabled_modules = await get_enabled_modules(bot_id)
            data["enabled_modules"] = enabled_modules
            
            # Load settings/messages into cache if not already loaded
            from utils.config_manager import config_manager
            if bot_id not in config_manager._settings:
                await config_manager.load_for_bot(bot_id)
            
            # Check if user is admin for this bot
            user_id = None
            if isinstance(event, Message) and event.from_user:
                user_id = event.from_user.id
            elif isinstance(event, CallbackQuery) and event.from_user:
                user_id = event.from_user.id
            
            if user_id:
                # Get bot admins from panel registry
                from database.panel_db import get_bot_by_id
                bot_info = await get_bot_by_id(bot_id)
                bot_admins = bot_info.get('admin_ids', []) if bot_info else []
                data["is_bot_admin"] = user_id in (bot_admins or [])
            else:
                data["is_bot_admin"] = False
                
            return await handler(event, data)
        finally:
            # Reset context to previous value
            if context_token is not None:
                from database.bot_methods import _current_bot_db
                _current_bot_db.reset(context_token)


# Handler-to-module mapping
# Maps handler patterns/names to module names for filtering
HANDLER_MODULE_MAP = {
    # Registration module handlers
    "process_name": "registration",
    "process_phone": "registration",
    
    # User profile module handlers
    "show_profile": "user_profile",
    "command_status": "user_profile",
    "show_receipts": "user_profile",
    "receipts_pagination": "user_profile",
    
    # Receipts module handlers  
    "process_receipt": "receipts",
    "confirm_receipt": "receipts",
    
    # Promo module handlers
    "process_promo_code": "promo",
    
    # FAQ module handlers
    "show_faq": "faq",
    "faq_how": "faq",
    "faq_limit": "faq",
    "faq_win": "faq",
    "faq_reject": "faq",
    "faq_dates": "faq",
    "faq_prizes": "faq",
    "faq_back": "faq",
    
    # Support module handlers
    "show_support": "support",
    
    # Admin module handlers
    "admin_handler": "admin",
    "broadcast_start": "admin",
    "raffle_start": "admin",
}

