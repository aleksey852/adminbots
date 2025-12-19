"""
Receipt Example Bot — Шаблон чекового промо-бота.

Бот = manifest.json + content.py. Никакого кода!
Использует модули: core, registration, receipts, raffle, admin
"""
from bots._base import BotBase

# Всё! Одна строка инициализации.
bot = BotBase(__file__)

# Экспорты для совместимости
manifest = bot.manifest
BOT_NAME = bot.name
BOT_VERSION = bot.version
BOT_MODULES = bot.modules
get_content = lambda: bot.content
get_manifest = lambda: bot.manifest

__all__ = ['bot', 'manifest', 'BOT_NAME', 'BOT_VERSION', 'BOT_MODULES', 'get_content', 'get_manifest']
