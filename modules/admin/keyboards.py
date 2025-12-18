"""Keyboards for Admin module"""
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

def _reply(*buttons, cols=2):
    b = ReplyKeyboardBuilder()
    for text in buttons:
        b.add(KeyboardButton(text=text) if isinstance(text, str) else text)
    b.adjust(cols)
    return b.as_markup(resize_keyboard=True)

from aiogram.types import KeyboardButton

def get_confirm_keyboard():
    return _reply("✅ Подтвердить", "❌ Отмена")

def get_schedule_keyboard():
    return _reply("🚀 Сейчас", "❌ Отмена")

def get_admin_broadcast_preview_keyboard():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_send"))
    b.add(InlineKeyboardButton(text="✏️ Изменить", callback_data="broadcast_edit"))
    b.add(InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel"))
    b.adjust(2)
    return b.as_markup()
