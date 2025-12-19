"""
Raffle Module - Raffle/Draw functionality for bot
Configurable: with or without intermediate raffles
"""
from typing import Dict, Any
from aiogram import F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
import logging

from modules.base import BotModule
from utils.config_manager import config_manager
import config

logger = logging.getLogger(__name__)


class RaffleModule(BotModule):
    """
    Raffle module with configurable intermediate raffles.
    
    Two modes:
    1. Final only - single raffle at the end of promotion
    2. With intermediate - periodic raffles during promotion + final
    """
    
    name = "raffle"
    version = "1.0.0"
    description = "Модуль розыгрышей призов"
    default_enabled = True
    
    settings_schema = {
        "intermediate_enabled": {
            "type": "checkbox",
            "label": "Промежуточные розыгрыши",
            "default": "false",
            "required": False,
            "help": "Включить периодические розыгрыши помимо финального"
        },
        "intermediate_period": {
            "type": "select",
            "label": "Периодичность",
            "default": "weekly",
            "required": False,
            "options": [
                {"value": "weekly", "label": "Еженедельно"},
                {"value": "monthly", "label": "Ежемесячно"},
            ],
            "help": "Как часто проводить промежуточные розыгрыши"
        }
    }
    
    default_messages = {
        "raffle_win": "🎉 Поздравляем! Вы выиграли: {prize}!",
        "raffle_lose": "К сожалению, в этот раз удача не на вашей стороне. Не расстраивайтесь, впереди ещё много возможностей!",
        "raffle_pending": "⏳ Розыгрыш скоро начнётся! Оставайтесь с нами.",
    }
    
    def _setup_handlers(self):
        """Setup raffle-related handlers (info, status checks)"""
        
        @self.router.message(F.text == "🎁 Розыгрыши")
        async def show_raffles_info(message: Message, bot_id: int = None):
            """Show raffle info to user"""
            settings = await self.get_settings(bot_id) if bot_id else {}
            intermediate_enabled = settings.get("intermediate_enabled", "false") == "true"
            
            if intermediate_enabled:
                period = settings.get("intermediate_period", "weekly")
                period_text = {
                    "daily": "ежедневно",
                    "weekly": "еженедельно",
                    "monthly": "ежемесячно"
                }.get(period, "периодически")
                
                text = (
                    f"🎁 <b>Розыгрыши в акции</b>\n\n"
                    f"📅 Промежуточные розыгрыши: <b>{period_text}</b>\n"
                    f"🏆 Финальный розыгрыш: в конце акции\n\n"
                    f"Чем больше билетов — тем выше шансы на победу!"
                )
            else:
                text = (
                    f"🎁 <b>Розыгрыш призов</b>\n\n"
                    f"🏆 Финальный розыгрыш состоится в конце акции.\n\n"
                    f"Чем больше билетов — тем выше шансы на победу!"
                )
            
            await message.answer(text, parse_mode="HTML")
    
    async def is_intermediate_raffle_enabled(self, bot_id: int) -> bool:
        """Check if intermediate raffles are enabled for this bot"""
        settings = await self.get_settings(bot_id)
        return settings.get("intermediate_enabled", "false") == "true"
    
    async def get_raffle_config(self, bot_id: int) -> Dict[str, Any]:
        """Get raffle configuration for this bot"""
        settings = await self.get_settings(bot_id)
        return {
            "intermediate_enabled": settings.get("intermediate_enabled", "false") == "true",
            "intermediate_period": settings.get("intermediate_period", "weekly"),
        }


# Module instance
raffle_module = RaffleModule()
