from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from bot_manager import bot_manager

class BotMiddleware(BaseMiddleware):
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
        if bot_id:
            data["bot_id"] = bot_id
        else:
            # Fallback or error?
            # If bot is not in manager (e.g. startup issue), we might ignore
            pass
            
        return await handler(event, data)
