"""Keyboards for Core module"""
from aiogram.types import KeyboardButton, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import config

def _reply(*buttons, cols=2):
    b = ReplyKeyboardBuilder()
    for text in buttons:
        b.add(KeyboardButton(text=text) if isinstance(text, str) else text)
    b.adjust(cols)
    return b.as_markup(resize_keyboard=True)

def get_cancel_keyboard():
    return _reply("❌ Отмена", cols=1)

def get_main_keyboard(is_admin: bool = False, bot_type: str = 'receipt'):
    buttons = []
    if bot_type == 'receipt':
        buttons.append("🧾 Загрузить чек")
    else:
        buttons.append("🔑 Ввести промокод")

    history_btn = "📋 Мои чеки" if bot_type == 'receipt' else "📋 Мои активации"
    buttons.extend(["👤 Мой профиль", "🎫 Мои билеты", history_btn, "ℹ️ FAQ", "🆘 Поддержка"])
    
    if is_admin:
        buttons.extend([
            "📊 Статистика", "📢 Рассылка", "🎁 Розыгрыш",
            "🏆 Победители", "📥 Экспорт победителей", "➕ Ручное добавление"
        ])
    return _reply(*buttons)

def get_support_keyboard():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(
        text="🆘 Написать в поддержку",
        url=f"https://t.me/{config.SUPPORT_TELEGRAM.replace('@', '')}"
    ))
    return b.as_markup()

def get_faq_keyboard(bot_type: str = 'receipt'):
    b = InlineKeyboardBuilder()
    items = [
        ("🎯 Как участвовать?", "faq_how"),
        ("🎲 Розыгрыши", "faq_raffle"),
        ("🧾 Лимиты" if bot_type == 'receipt' else "🔢 Лимиты", "faq_limit"),
        ("🏆 Про выигрыш", "faq_win"),
        ("❌ Не принято?", "faq_reject"),
        ("📅 Сроки", "faq_dates"),
        ("🎁 Призы", "faq_prizes"),
    ]
    for text, data in items:
        b.add(InlineKeyboardButton(text=text, callback_data=data))
    b.adjust(2)
    return b.as_markup()

def get_faq_back_keyboard():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="◀️ Назад", callback_data="faq_back"))
    return b.as_markup()

def get_receipts_pagination_keyboard(page: int, total_pages: int):
    b = InlineKeyboardBuilder()
    if page > 1:
        b.add(InlineKeyboardButton(text="◀️", callback_data=f"receipts_page_{page-1}"))
    b.add(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="receipts_current"))
    if page < total_pages:
        b.add(InlineKeyboardButton(text="▶️", callback_data=f"receipts_page_{page+1}"))
    b.adjust(3)
    return b.as_markup()
