"""
Raffle Module - Raffle/Draw functionality for bot
Raffles are created and scheduled manually by admin through the admin panel.
"""
from typing import Dict, Any
from aiogram import F
from aiogram.types import Message
import logging

from core.module_base import BotModule
import config

logger = logging.getLogger(__name__)


class RaffleModule(BotModule):
    """
    Raffle module for prize draws.
    
    Raffles are created manually by admin - no automatic scheduling.
    Admin decides when to run raffles through the admin panel.
    """
    
    name = "raffle"
    version = "2.0.0"
    description = "Модуль розыгрышей призов"
    default_enabled = True
    dependencies = ["core"]
    
    # Menu button
    menu_buttons = [
        {"text": "🎟 Мои билеты", "order": 30}
    ]
    
    # State protection
    states = []
    state_timeout = 600
    
    # No settings - admin creates raffles manually
    settings_schema = {}
    
    default_messages = {
        "raffle_win": "🎉 Поздравляем! Ты выиграл: {prize}!",
        "raffle_lose": "В этот раз не повезло 😔 Но впереди ещё розыгрыши — копи билеты!",
        "raffle_info": "🎁 Розыгрыши проводит администратор\n\n🏆 Чем больше билетов — тем выше шанс!",
    }
    
    def _setup_handlers(self):
        """Setup raffle-related handlers"""
        
        @self.router.message(F.text == "🎁 Розыгрыши")
        async def show_raffles_info(message: Message, bot_id: int = None):
            """Show raffle info to user"""
            from utils.config_manager import config_manager
            
            text = config_manager.get_message(
                'raffle_info',
                self.default_messages['raffle_info'],
                bot_id=bot_id
            )
            await message.answer(text)


# Module instance
raffle_module = RaffleModule()
