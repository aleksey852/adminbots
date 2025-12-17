"""
Bot Middleware - Injects bot_id, enabled modules and admin status into handlers
"""
from typing import Callable, Dict, Any, Awaitable, Set
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from bot_manager import bot_manager
import logging

logger = logging.getLogger(__name__)

# Cache for enabled modules per bot (refreshed periodically)
_enabled_modules_cache: Dict[int, Set[str]] = {}


async def get_enabled_modules(bot_id: int) -> Set[str]:
    """Get enabled modules for a bot, with caching."""
    if bot_id in _enabled_modules_cache:
        return _enabled_modules_cache[bot_id]
    
    from database import get_bot_enabled_modules
    modules = await get_bot_enabled_modules(bot_id)
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
        
        # Load enabled modules for this bot
        enabled_modules = await get_enabled_modules(bot_id)
        data["enabled_modules"] = enabled_modules
        
        # Check if user is admin for this bot
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id
        
        if user_id:
            from database import is_bot_admin
            data["is_bot_admin"] = await is_bot_admin(user_id, bot_id)
        else:
            data["is_bot_admin"] = False
            
        return await handler(event, data)


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

