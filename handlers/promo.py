import re

from aiogram import Router, F
from aiogram.types import Message
from bot_manager import bot_manager
from utils.config_manager import config_manager
from database import methods
import config

router = Router()

# Promo code: exactly 12 alphanumeric characters
PROMO_CODE_LENGTH = 12
CODE_PATTERN = re.compile(r"^[A-Za-z0-9]{12}$")


def normalize_code(text: str) -> str:
    """Clean up code: remove spaces, dashes, convert to upper"""
    return re.sub(r'[\s\-_]', '', text).upper().strip()


@router.message(F.text == "🔑 Ввести промокод")
async def promo_prompt(message: Message, bot_id: int):
    """Show promo code entry instruction"""
    if bot_manager.bot_types.get(bot_id) != 'promo':
        return

    text = config_manager.get_message(
        'promo_prompt',
        "🔑 Введите промокод из 12 символов\n\n💡 Пример: ABCD12345678",
        bot_id=bot_id,
    )
    await message.answer(text)


@router.message(F.text)
async def process_promo_code(message: Message, bot_id: int):
    """Handle text messages for Promo bots"""
    
    # Check if this bot is a promo bot
    bot_type = bot_manager.bot_types.get(bot_id)
    if bot_type != 'promo':
        return  # Let other handlers process

    # Skip menu buttons
    if message.text.startswith(('🔑', '👤', '📋', 'ℹ️', '🆘', '📊', '📢', '🎁', '🏆', '📥', '➕', '❌', '🏠')):
        return

    if not config.is_promo_active():
        promo_ended_msg = config_manager.get_message(
            'promo_ended',
            "🏁 Акция завершена {date}\n\nСпасибо за участие!",
            bot_id=bot_id
        ).format(date=config.PROMO_END_DATE)
        await message.answer(promo_ended_msg)
        return

    # Normalize: remove spaces, dashes, uppercase
    code_text = normalize_code(message.text)

    # Check format
    if len(code_text) != PROMO_CODE_LENGTH:
        if len(message.text.strip()) >= 4:  # Only show error if it looks like a code attempt
            msg = config_manager.get_message(
                'promo_wrong_format',
                "⚠️ Промокод должен содержать ровно 12 символов\n\n"
                "Вы ввели: {length} символов\n"
                "💡 Пример: ABCD12345678",
                bot_id=bot_id
            ).format(length=len(code_text))
            await message.answer(msg)
        return
    
    if not CODE_PATTERN.match(code_text):
        msg = config_manager.get_message(
            'promo_invalid_chars',
            "⚠️ Промокод может содержать только буквы и цифры\n\n💡 Пример: ABCD12345678",
            bot_id=bot_id
        )
        await message.answer(msg)
        return

    # Check code in database (case-insensitive via normalized code)
    promo = await methods.get_promo_code(code_text, bot_id)
    
    # Also try original case if not found
    if not promo:
        promo = await methods.get_promo_code(message.text.strip(), bot_id)
    
    if not promo:
        msg = config_manager.get_message(
            'promo_not_found',
            "❌ Промокод не найден\n\nПроверьте правильность ввода или обратитесь в поддержку",
            bot_id=bot_id
        )
        await message.answer(msg)
        return
        
    if promo['status'] != 'active':
        msg = config_manager.get_message(
            'promo_already_used',
            "⚠️ Этот промокод уже был использован",
            bot_id=bot_id
        )
        await message.answer(msg)
        return

    # Ensure user exists
    db_user = await methods.get_user(message.from_user.id, bot_id)
    if not db_user:
        fallback_phone = "promo_auto_reg"  # Placeholder for auto-registered promo users
        await methods.add_user(
            message.from_user.id, 
            message.from_user.username or "", 
            message.from_user.full_name, 
            fallback_phone, 
            bot_id
        )
        db_user = await methods.get_user(message.from_user.id, bot_id)

    # Use Code
    if await methods.use_promo_code(promo['id'], db_user['id']):
        tickets = promo.get('tickets', 1)
        
        # Create virtual receipt for tracking
        await methods.add_receipt(
            user_id=db_user['id'],
            status='valid',
            data={'code': code_text},
            bot_id=bot_id,
            fiscal_drive_number='PROMO',
            fiscal_document_number=f"CODE-{promo['id']}",
            fiscal_sign='SIGN',
            total_sum=0,
            tickets=tickets,
            raw_qr=code_text
        )
        
        # Get total tickets
        total_tickets = await methods.get_user_tickets_count(db_user['id'])
        
        msg = config_manager.get_message(
            'promo_activated',
            "✅ Промокод активирован!\n\n"
            "🎟 Получено билетов: {tickets}\n"
            "📊 Всего билетов: {total}",
            bot_id=bot_id
        ).format(tickets=tickets, total=total_tickets)
        await message.answer(msg)
    else:
        msg = config_manager.get_message(
            'promo_activation_error',
            "❌ Ошибка при активации кода. Попробуйте ещё раз.",
            bot_id=bot_id
        )
        await message.answer(msg)

