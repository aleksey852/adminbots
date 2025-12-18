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
    CODE_PATTERN = re.compile(r"^[A-Za-z0-9]{12}$")
    
    def normalize_code(self, text: str) -> str:
        return re.sub(r'[\s\-_]', '', text).upper().strip()
    
    def _setup_handlers(self):
        """Setup promo handlers"""
        
        @self.router.message(F.text == "🔑 Ввести промокод")
        async def promo_prompt(message: Message, bot_id: int):
            if bot_manager.bot_types.get(bot_id) != 'promo': return
            text = config_manager.get_message('promo_prompt', "🔑 Введите промокод из 12 символов\n\n💡 Пример: ABCD12345678", bot_id=bot_id)
            await message.answer(text)

        @self.router.message(F.text)
        async def process_promo_code(message: Message, bot_id: int):
            if bot_manager.bot_types.get(bot_id) != 'promo': return
            if message.text.startswith(('🔑', '👤', '📋', 'ℹ️', '🆘', '📊', '📢', '🎁', '🏆', '📥', '➕', '❌', '🏠')): return
            
            if not config.is_promo_active():
                await message.answer(config_manager.get_message('promo_ended', "🏁 Акция завершена {date}", bot_id=bot_id).format(date=config.PROMO_END_DATE))
                return

            code_text = self.normalize_code(message.text)
            if len(code_text) != self.PROMO_CODE_LENGTH:
                if len(message.text.strip()) >= 4:
                    msg = config_manager.get_message('promo_wrong_format', "⚠️ Промокод должен содержать ровно 12 символов\nВы ввели: {length}\n💡 Пример: ABCD12345678", bot_id=bot_id).format(length=len(code_text))
                    await message.answer(msg)
                return
            
            if not self.CODE_PATTERN.match(code_text):
                await message.answer(config_manager.get_message('promo_invalid_chars', "⚠️ Промокод может содержать только буквы и цифры", bot_id=bot_id))
                return

            promo = await bot_methods.get_promo_code(code_text) or await bot_methods.get_promo_code(message.text.strip())
            if not promo:
                await message.answer(config_manager.get_message('promo_not_found', "❌ Промокод не найден", bot_id=bot_id))
                return
            if promo['status'] != 'active':
                await message.answer(config_manager.get_message('promo_already_used', "⚠️ Этот промокод уже был использован", bot_id=bot_id))
                return

            db_user = await bot_methods.get_user(message.from_user.id)
            if not db_user:
                await bot_methods.add_user(message.from_user.id, message.from_user.username or "", message.from_user.full_name, "promo_auto_reg")
                db_user = await bot_methods.get_user(message.from_user.id)

            if await bot_methods.use_promo_code(promo['id'], db_user['id']):
                tickets = promo.get('tickets', 1)
                await bot_methods.add_receipt(user_id=db_user['id'], status='valid', data={'code': code_text}, fiscal_drive_number='PROMO', fiscal_document_number=f"CODE-{promo['id']}", fiscal_sign='SIGN', total_sum=0, tickets=tickets, raw_qr=code_text, product_name=f"Промокод: {code_text[:8]}...")
                total_tickets = await bot_methods.get_user_tickets_count(db_user['id'])
                msg = config_manager.get_message('promo_activated', "✅ Промокод активирован!\n🎟 Получено билетов: {tickets}\n📊 Всего билетов: {total}", bot_id=bot_id).format(tickets=tickets, total=total_tickets)
                await message.answer(msg)
            else:
                await message.answer(config_manager.get_message('promo_activation_error', "❌ Ошибка при активации кода.", bot_id=bot_id))

# Module instance
promo_module = PromoModule()
