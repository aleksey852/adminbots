"""
Promo Module - Promo code activation
"""
from aiogram import Router, F
from aiogram.types import Message
import re
import logging

from modules.base import BotModule
from bot_manager import bot_manager
from utils.config_manager import config_manager
from database import bot_methods
import config

logger = logging.getLogger(__name__)

class PromoModule(BotModule):
    """Promo code activation module"""
    
    name = "promo"
    version = "1.0.0"
    description = "Модуль активации промокодов"
    default_enabled = True
    
    PROMO_CODE_LENGTH = 12
    # Allows generic alphanumeric, will be normalized
    CODE_PATTERN = re.compile(r"^[A-Z0-9]{12}$")
    
    default_messages = {
        "promo_prompt": "🔑 Введите промокод из 12 символов\n\n💡 Пример: ABCD12345678",
        "promo_ended": "🏁 Акция завершена {date}",
        "promo_wrong_format": "⚠️ Промокод должен содержать ровно 12 символов\nВы ввели: {length}\n💡 Пример: ABCD12345678",
        "promo_invalid_chars": "⚠️ Промокод может содержать только буквы и цифры",
        "promo_not_found": "❌ Промокод не найден или введен неверно",
        "promo_already_used": "⚠️ Этот промокод уже был использован",
        "promo_db_error": "⚠️ Временная ошибка. Попробуйте позже.",
        "promo_activated": "✅ Промокод активирован!\n🎟 Получено билетов: {tickets}\n📊 Всего билетов: {total}",
        "promo_activation_error": "❌ Ошибка при активации кода.",
    }
    
    def normalize_code(self, text: str) -> str:
        # Remove whitespace, dashes, underscores
        clean = re.sub(r'[\s\-_]', '', text).upper()
        return clean
    
    def _setup_handlers(self):
        """Setup promo handlers"""
        
        @self.router.message(F.text == "🔑 Ввести промокод")
        async def promo_prompt(message: Message, bot_id: int = None):
            if not bot_id: return
            if bot_manager.bot_types.get(bot_id) != 'promo': return
            
            text = config_manager.get_message('promo_prompt', self.default_messages['promo_prompt'], bot_id=bot_id)
            await message.answer(text)

        @self.router.message(F.text)
        async def process_promo_code(message: Message, bot_id: int = None):
            if not bot_id: return
            if bot_manager.bot_types.get(bot_id) != 'promo': return
            
            # Ignore commands and menu items
            if message.text.startswith(('/', '🔑', '👤', '📋', 'ℹ️', '🆘', '📊', '📢', '🎁', '🏆', '📥', '➕', '❌', '🏠')): 
                return
            
            # Check if active
            if not config.is_promo_active():
                msg = config_manager.get_message(
                    'promo_ended', 
                    self.default_messages['promo_ended'], 
                    bot_id=bot_id
                ).format(date=config.PROMO_END_DATE)
                await message.answer(msg)
                return

            code_text = self.normalize_code(message.text)
            
            # Length Check
            if len(code_text) != self.PROMO_CODE_LENGTH:
                # Only reply error if it looks like an attempt (>= 4 chars), to avoid noise
                if len(message.text.strip()) >= 4:
                    msg = config_manager.get_message(
                        'promo_wrong_format', 
                        self.default_messages['promo_wrong_format'], 
                        bot_id=bot_id
                    ).format(length=len(code_text))
                    await message.answer(msg)
                return
            
            # Character Check
            if not self.CODE_PATTERN.match(code_text):
                await message.answer(config_manager.get_message('promo_invalid_chars', self.default_messages['promo_invalid_chars'], bot_id=bot_id))
                return

            try:
                # Check DB
                promo = await bot_methods.get_promo_code(code_text)
                
                if not promo:
                    await message.answer(config_manager.get_message('promo_not_found', self.default_messages['promo_not_found'], bot_id=bot_id))
                    return
                
                if promo['status'] != 'active':
                    await message.answer(config_manager.get_message('promo_already_used', self.default_messages['promo_already_used'], bot_id=bot_id))
                    return

                # Activate
                db_user = await bot_methods.get_user(message.from_user.id)
                if not db_user:
                    # Auto register if somehow missed
                    await bot_methods.add_user(message.from_user.id, message.from_user.username or "", message.from_user.full_name, "promo_auto_reg")
                    db_user = await bot_methods.get_user(message.from_user.id)

                # Use code
                if await bot_methods.use_promo_code(promo['id'], db_user['id']):
                    tickets = promo.get('tickets', 1)
                    
                    # Log as a "valid receipt" for consistency in stats/logic
                    # Or just rely on promo_codes table status? 
                    # Existing logic added a receipt entry, which is good for unifying logic.
                    await bot_methods.add_receipt(
                        user_id=db_user['id'], 
                        status='valid', 
                        data={'code': code_text}, 
                        fiscal_drive_number='PROMO', 
                        fiscal_document_number=f"CODE-{promo['id']}", 
                        fiscal_sign='SIGN', 
                        total_sum=0, 
                        tickets=tickets, 
                        raw_qr=code_text, 
                        product_name=f"Промокод: {code_text[:8]}..."
                    )
                    
                    total_tickets = await bot_methods.get_user_tickets_count(db_user['id'])
                    
                    msg = config_manager.get_message(
                        'promo_activated', 
                        self.default_messages['promo_activated'], 
                        bot_id=bot_id
                    ).format(tickets=tickets, total=total_tickets)
                    await message.answer(msg)
                else:
                    await message.answer(config_manager.get_message('promo_activation_error', self.default_messages['promo_activation_error'], bot_id=bot_id))
                    
            except Exception as e:
                logger.error(f"Error processing promo code: {e}")
                await message.answer(config_manager.get_message('promo_db_error', self.default_messages['promo_db_error'], bot_id=bot_id))

# Module instance
promo_module = PromoModule()
