"""
Promo Module - Promo code activation
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
import re
import logging

from core.module_base import BotModule
from bot_manager import bot_manager
from utils.config_manager import config_manager
from database import bot_methods
import config

logger = logging.getLogger(__name__)

class PromoModule(BotModule):
    """Promo code activation module"""
    
    name = "promo"
    version = "2.0.0"
    description = "Модуль активации промокодов"
    default_enabled = True
    dependencies = ["core", "profile"]
    
    # Menu button for dynamic menu
    menu_buttons = [
        {"text": "🔑 Ввести промокод", "order": 20}
    ]
    
    # State protection
    states = []  # No FSM states, just processes text
    state_timeout = 600
    
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

        @self.router.callback_query(F.data.startswith("activate_code:"))
        async def activate_code_callback(callback: CallbackQuery, bot_id: int = None):
            """Handle inline button activation of promo code"""
            if not bot_id: return
            if bot_manager.bot_types.get(bot_id) != 'promo': return
            
            # Extract code from callback data
            code_text = callback.data.split(":", 1)[1] if ":" in callback.data else ""
            if not code_text:
                await callback.answer("Ошибка: код не найден", show_alert=True)
                return
            
            try:
                # Check DB
                promo = await bot_methods.get_promo_code(code_text)
                
                if not promo:
                    await callback.answer("❌ Промокод не найден", show_alert=True)
                    return
                
                if promo['status'] != 'active':
                    await callback.answer("⚠️ Промокод уже использован", show_alert=True)
                    # Update message to show it's already activated
                    await callback.message.edit_text(
                        f"✅ Промокод уже активирован!\n\n🔑 Код: <code>{code_text}</code>",
                        parse_mode="HTML"
                    )
                    return

                # Get/create user
                db_user = await bot_methods.get_user(callback.from_user.id)
                if not db_user:
                    await bot_methods.add_user(
                        callback.from_user.id, 
                        callback.from_user.username or "", 
                        callback.from_user.full_name, 
                        "promo_auto_reg"
                    )
                    db_user = await bot_methods.get_user(callback.from_user.id)

                # Use code
                if await bot_methods.use_promo_code(promo['id'], db_user['id']):
                    tickets = promo.get('tickets', 1)
                    
                    # Add receipt for stats
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
                    
                    # Update message to show success
                    await callback.message.edit_text(
                        f"✅ <b>Промокод активирован!</b>\n\n"
                        f"🔑 Код: <code>{code_text}</code>\n"
                        f"🎟 Получено билетов: {tickets}\n"
                        f"📊 Всего билетов: {total_tickets}",
                        parse_mode="HTML"
                    )
                    await callback.answer("✅ Промокод активирован!")
                else:
                    await callback.answer("❌ Ошибка при активации", show_alert=True)
                    
            except Exception as e:
                logger.error(f"Error activating promo code via callback: {e}")
                await callback.answer("⚠️ Временная ошибка. Попробуйте позже.", show_alert=True)

        @self.router.message(F.text, StateFilter(None))
        async def process_promo_code(message: Message, bot_id: int = None):
            if not bot_id: return
            if bot_manager.bot_types.get(bot_id) != 'promo': return
            
            # Ignore commands and menu items
            if message.text.startswith(('/', '🔑', '👤', '📋', 'ℹ️', '🆘', '📊', '📢', '🎁', '🏆', '📥', '➕', '❌', '🏠')): 
                return
            
            # Check if active
            if not await config.is_promo_active_async(bot_id):
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
