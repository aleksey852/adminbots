"""
Subscription Module - Checks user subscription to a channel
"""
from typing import Dict, Any
from modules.base import BotModule
import config

class SubscriptionModule(BotModule):
    """
    Module for checking channel subscription.
    """
    
    name = "subscription"
    version = "1.0.0"
    description = "Проверка подписки на канал"
    default_enabled = False
    
    settings_schema = {
        "SUBSCRIPTION_REQUIRED": {
            "type": "checkbox",
            "label": "Требовать подписку",
            "default": "false",
            "required": False
        },
        "SUBSCRIPTION_CHANNEL_ID": {
            "type": "text",
            "label": "ID канала (напр. -100...)",
            "default": "",
            "required": False
        },
        "SUBSCRIPTION_CHANNEL_URL": {
            "type": "text",
            "label": "Ссылка на канал",
            "default": "",
            "required": False
        }
    }
    
    default_messages = {
        "sub_check_success": "✅ Подписка подтверждена!",
        "sub_check_fail": "❌ Вы ещё не подписаны на канал!",
        "sub_warning": "⚠️ Для участия в акции необходимо подписаться на наш канал!",
    }
    
    def _setup_handlers(self):
        # Logic is mainly in middleware/utils currently, 
        # but we can eventually move it here or keep it as configuration holder.
        pass

subscription_module = SubscriptionModule()
