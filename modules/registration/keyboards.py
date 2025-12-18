"""Keyboards for Registration module"""
from aiogram.types import KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

def _reply(*buttons, cols=2):
    b = ReplyKeyboardBuilder()
    for text in buttons:
        b.add(KeyboardButton(text=text) if isinstance(text, str) else text)
    b.adjust(cols)
    return b.as_markup(resize_keyboard=True)

def get_start_keyboard():
    return _reply("🚀 Начать", cols=1)

def get_contact_keyboard():
    return _reply(
        KeyboardButton(text="📱 Отправить номер", request_contact=True),
        "❌ Отмена", cols=1
    )
