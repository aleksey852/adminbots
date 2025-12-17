from aiogram import Router, F
from aiogram.types import Message
from bot_manager import bot_manager
from database import methods

router = Router()

@router.message(F.text, ~F.text.startswith("/"))
async def process_promo_code(message: Message, bot_id: int):
    """Handle text messages for Promo bots"""
    
    # Check if this bot is a promo bot
    bot_type = bot_manager.bot_types.get(bot_id)
    if bot_type != 'promo':
        return # Ignore (let other handlers or default fallback handle it)

    code_text = message.text.strip()
    user_id = message.from_user.id
    
    # Check code
    promo = await methods.get_promo_code(code_text, bot_id)
    
    if not promo:
        await message.answer("❌ Промокод не найден или неверен.")
        return
        
    if promo['status'] != 'active':
        await message.answer("⚠️ Этот промокод уже был использован.")
        return

    # Ensure user exists (if they just started chatting without /start)
    db_user = await methods.get_user(message.from_user.id, bot_id)
    if not db_user:
        # Phone is mandatory in schema, use a safe placeholder for promo-only flow
        fallback_phone = str(message.from_user.id)
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
        # Create virtual receipt to grant ticket(s) and track stats
        tickets = promo.get('tickets', 1)
        
        # We need unique Fiscal Data. We use 'PROMO' + Code ID
        # Since code ID is unique PK, this receipt will be unique too.
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
        
        await message.answer(f"✅ Промокод активирован!\n🎟 Вы получили билетов: {tickets}")
    else:
        await message.answer("❌ Ошибка при активации кода. Попробуйте еще раз.")
