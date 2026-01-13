"""
Statistics Module - Stats for admin panel and bot
"""
from typing import Dict, Any
from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message
import logging
from datetime import datetime, timedelta

from core.module_base import BotModule
from database.bot_methods import (
    get_stats, get_participants_count, get_total_tickets_count,
    get_promo_stats, get_stats_by_days
)
from utils.config_manager import config_manager
import config

logger = logging.getLogger(__name__)


class StatisticsModule(BotModule):
    """Statistics for admin panel and bot"""
    
    name = "statistics"
    version = "1.0.0"
    description = "Статистика бота"
    default_enabled = True
    dependencies = ["core"]
    
    # State protection
    states = []
    state_timeout = 600
    
    default_messages = {
        "stats_title": "📊 Статистика бота",
        "stats_users": "👥 Пользователи",
        "stats_activations": "🔑 Активации",
        "stats_tickets": "🎟 Билетов в системе: {count}",
        "stats_codes": "📦 Промокодов осталось: {count}",
    }
    
    def _setup_handlers(self):
        """Setup statistics handlers (admin only)"""
        
        @self.router.message(Command("stats"))
        async def show_stats(message: Message, bot_id: int = None):
            """Show statistics (admin only via /stats command)"""
            if not bot_id or not config.is_admin(message.from_user.id):
                return
            
            # Gather stats
            stats = await get_stats()
            promo_stats = await get_promo_stats()
            total_tickets = await get_total_tickets_count()
            participants = await get_participants_count()
            
            # Calculate periods
            users_total = stats.get('total_users', 0)
            users_today = stats.get('users_today', 0)
            
            receipts_total = stats.get('valid_receipts', 0)
            receipts_today = stats.get('receipts_today', 0)
            
            # Get weekly/monthly from stats_by_days
            daily_stats = await get_stats_by_days(30)
            
            users_7d = sum(row['users'] for row in daily_stats[-7:]) if daily_stats else 0
            users_14d = sum(row['users'] for row in daily_stats[-14:]) if daily_stats else 0
            users_30d = sum(row['users'] for row in daily_stats) if daily_stats else 0
            
            activations_7d = sum(row['receipts'] for row in daily_stats[-7:]) if daily_stats else 0
            activations_14d = sum(row['receipts'] for row in daily_stats[-14:]) if daily_stats else 0
            activations_30d = sum(row['receipts'] for row in daily_stats) if daily_stats else 0
            
            # Build message
            text = "📊 Статистика бота\n\n"
            
            text += "👥 ПОЛЬЗОВАТЕЛИ\n"
            text += f"   • Всего: {users_total}\n"
            text += f"   • За день: +{users_today}\n"
            text += f"   • За 7 дней: +{users_7d}\n"
            text += f"   • За 14 дней: +{users_14d}\n"
            text += f"   • За месяц: +{users_30d}\n"
            text += "\n"
            
            text += "🔑 АКТИВАЦИИ\n"
            text += f"   • Всего: {receipts_total}\n"
            text += f"   • За день: +{receipts_today}\n"
            text += f"   • За 7 дней: +{activations_7d}\n"
            text += f"   • За 14 дней: +{activations_14d}\n"
            text += f"   • За месяц: +{activations_30d}\n"
            text += "\n"
            
            text += "─────────────────────\n"
            text += f"🎟 Билетов в системе: {total_tickets}\n"
            text += f"🎯 Участников: {participants}\n"
            text += f"📦 Кодов осталось: {promo_stats.get('active', 0)}\n"
            text += f"🏆 Победителей: {stats.get('total_winners', 0)}\n"
            
            await message.answer(text)
    
    async def get_status(self, bot_id: int) -> Dict[str, Any]:
        """Return module status for monitoring dashboard"""
        stats = await get_stats()
        promo_stats = await get_promo_stats()
        
        return {
            **await super().get_status(bot_id),
            "metrics": {
                "users_total": stats.get('total_users', 0),
                "users_today": stats.get('users_today', 0),
                "activations_total": stats.get('valid_receipts', 0),
                "activations_today": stats.get('receipts_today', 0),
                "tickets_total": await get_total_tickets_count(),
                "codes_remaining": promo_stats.get('active', 0),
            }
        }


# Module instance
statistics_module = StatisticsModule()
