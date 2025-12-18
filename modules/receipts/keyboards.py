"""Keyboards for Receipts module"""
from aiogram.types import KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

def _reply(*buttons, cols=2):
    b = ReplyKeyboardBuilder()
    for text in buttons:
        b.add(KeyboardButton(text=text) if isinstance(text, str) else text)
    b.adjust(cols)
    return b.as_markup(resize_keyboard=True)

def get_receipt_continue_keyboard():
    return _reply("🧾 Ещё чек", "🏠 В меню")

def get_cancel_keyboard():
    return _reply("❌ Отмена", cols=1)
