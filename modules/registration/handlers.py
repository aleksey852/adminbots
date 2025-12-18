"""
Registration Module - User registration flow
"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
import re
import logging

from modules.base import BotModule
from utils.states import Registration
from .keyboards import get_contact_keyboard, get_start_keyboard
from modules.core.keyboards import get_main_keyboard
from database.bot_methods import add_user
from utils.config_manager import config_manager
from bot_manager import bot_manager
import config

logger = logging.getLogger(__name__)

class RegistrationModule(BotModule):
    """User registration module"""
    
    name = "registration"
    version = "1.0.0"
    description = "Модуль регистрации пользователей"
    default_enabled = True
    
    default_messages = {
        "reg_cancel": "Хорошо! Возвращайтесь 👋",
        "reg_name_error": "Введите имя (2-100 символов)",
        "reg_phone_prompt": "Отлично, {name}! 👋\n\nОтправьте номер телефона:",
        "reg_phone_error": "❌ Неверный формат. Введите в международном формате, например +79991234567",
        "reg_phone_request": "Отправьте номер телефона",
        "reg_success": "✅ Регистрация завершена!",
        "reg_success_promo": "✅ Регистрация завершена!\n\nОтправьте промокод сообщением в этот чат.\n\nАкция: {start} — {end}\n\n👇 Введите промокод",
    }
    
    # E.164-ish validator
    # Allows + (optional) followed by 10-15 digits
    PHONE_PATTERN = re.compile(r'^\+?[1-9]\d{9,14}$')
    
    def _setup_handlers(self):
        """Setup registration handlers"""
        
        @self.router.message(Registration.name)
        async def process_name(message: Message, state: FSMContext, bot_id: int = None):
            if message.text == "❌ Отмена":
                await state.clear()
                msg = config_manager.get_message('reg_cancel', self.default_messages['reg_cancel'], bot_id=bot_id)
                await message.answer(msg, reply_markup=get_start_keyboard())
                return
            
            if not message.text or len(message.text) < 2 or len(message.text) > 100:
                msg = config_manager.get_message('reg_name_error', self.default_messages['reg_name_error'], bot_id=bot_id)
                await message.answer(msg)
                return
            
            await state.update_data(name=message.text.strip(), bot_id=bot_id)
            prompt = config_manager.get_message(
                'reg_phone_prompt',
                self.default_messages['reg_phone_prompt'],
                bot_id=bot_id
            ).format(name=message.text)
            
            await message.answer(prompt, reply_markup=get_contact_keyboard())
            await state.set_state(Registration.phone)
        
        @self.router.message(Registration.phone)
        async def process_phone(message: Message, state: FSMContext, bot_id: int = None):
            if not bot_id:
                await message.answer("Ошибка: бот не идентифицирован")
                return

            if message.text == "❌ Отмена":
                await state.clear()
                msg = config_manager.get_message('reg_cancel', self.default_messages['reg_cancel'], bot_id=bot_id)
                await message.answer(msg, reply_markup=get_start_keyboard())
                return
            
            phone = None
            if message.contact:
                phone = message.contact.phone_number
                # Contact might come without +, but usually it's clean
                if not phone.startswith('+'):
                     phone = '+' + phone
            elif message.text:
                # 1. Strip whitespace
                text = message.text.strip()
                
                # 2. Check basic validity (digits, maybe +, spaces, parens, dashes)
                # Remove common separators
                clean = re.sub(r'[\s\-\(\)]', '', text)
                
                # 3. Handle Russian 8 suffix logic (8999... -> 7999...)
                # If starts with 8 and is 11 digits, replace 8 with 7
                if len(clean) == 11 and clean.startswith('8'):
                     clean = '7' + clean[1:]
                
                # 4. Final Validation: must be digits only now.
                # Must be 10-15 digits. Even 10 is risky without country code, but some users might try.
                # Let's enforce international format -> we expect roughly 11+ digits usually.
                # If user entered 9991234567 (10 digits), we assume +7 for RU context if needed?
                # No, that's dangerous. Let's stick to 11-15 digits for safety or strict specific codes.
                # But for general bot, let's accept 10-15 and if it doesn't have country code, prepend +? 
                
                # If clean starts with +, remove it for digit count check
                if clean.startswith('+'):
                    clean = clean[1:]
                
                if not clean.isdigit():
                    msg = config_manager.get_message('reg_phone_error', self.default_messages['reg_phone_error'], bot_id=bot_id)
                    await message.answer(msg)
                    return
                
                if len(clean) < 10 or len(clean) > 15:
                    msg = config_manager.get_message('reg_phone_error', self.default_messages['reg_phone_error'], bot_id=bot_id)
                    await message.answer(msg)
                    return

                phone = '+' + clean
            else:
                msg = config_manager.get_message('reg_phone_request', self.default_messages['reg_phone_request'], bot_id=bot_id)
                await message.answer(msg)
                return
            
            data = await state.get_data()
            await add_user(
                telegram_id=message.from_user.id,
                username=message.from_user.username or "",
                full_name=data.get("name", "Пользователь"),
                phone=phone
            )
            
            await state.clear()
            
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            
            if bot_type == 'promo':
                msg_key = 'reg_success_promo'
                default_msg = self.default_messages['reg_success_promo']
            else:
                msg_key = 'reg_success'
                default_msg = self.default_messages['reg_success']
            
            success_msg = config_manager.get_message(
                msg_key,
                default_msg,
                bot_id=bot_id
            ).format(start=config.PROMO_START_DATE, end=config.PROMO_END_DATE)
            
            await message.answer(
                success_msg,
                reply_markup=get_main_keyboard(config.is_admin(message.from_user.id), bot_type)
            )

# Module instance
registration_module = RegistrationModule()
