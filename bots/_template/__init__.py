"""
Bot Template — Минимальный бот на основе BotBase.

Бот = manifest.json + content.py. Никакого кода!
Вся логика через модули из библиотеки modules/
"""
from bots._base import BotBase

# Инициализация бота из текущей папки
bot = BotBase(__file__)

# Экспорты для совместимости
manifest = bot.manifest
BOT_NAME = bot.name
BOT_VERSION = bot.version
BOT_MODULES = bot.modules

def get_content():
    """Get content module for this bot"""
    return bot.content

def get_manifest() -> dict:
    """Get full manifest data"""
    return bot.manifest

__all__ = ['bot', 'manifest', 'BOT_NAME', 'BOT_VERSION', 'BOT_MODULES', 'get_content', 'get_manifest']
