"""
Registration Module - User registration flow
"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
import re

from modules.base import BotModule
from utils.states import Registration
from keyboards import get_contact_keyboard, get_main_keyboard, get_start_keyboard, get_cancel_keyboard
from database import add_user
from utils.config_manager import config_manager
import config


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
        "reg_phone_error": "❌ Неверный формат. Введите как +79991234567",
        "reg_phone_request": "Отправьте номер телефона",
        "reg_success": "✅ Регистрация завершена!\n\n1. Купите акционные товары\n2. Сфотографируйте QR-код\n3. Загрузите сюда\n\nАкция: {start} — {end}\n\n👇 Загрузите первый чек",
    }
    
    PHONE_PATTERN = re.compile(r'^\+?[0-9]{10,15}$')
    
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
            elif message.text:
                clean = re.sub(r'\D', '', message.text)
                if not self.PHONE_PATTERN.match(clean) and not self.PHONE_PATTERN.match(message.text.strip()):
                    msg = config_manager.get_message('reg_phone_error', self.default_messages['reg_phone_error'], bot_id=bot_id)
                    await message.answer(msg)
                    return
                phone = message.text.strip()
            else:
                msg = config_manager.get_message('reg_phone_request', self.default_messages['reg_phone_request'], bot_id=bot_id)
                await message.answer(msg)
                return
            
            data = await state.get_data()
            await add_user(
                telegram_id=message.from_user.id,
                username=message.from_user.username or "",
                full_name=data.get("name", "Пользователь"),
                phone=phone,
                bot_id=bot_id
            )
            
            await state.clear()
            success_msg = config_manager.get_message(
                'reg_success',
                self.default_messages['reg_success'],
                bot_id=bot_id
            ).format(start=config.PROMO_START_DATE, end=config.PROMO_END_DATE)
            
            await message.answer(
                success_msg,
                reply_markup=get_main_keyboard(config.is_admin(message.from_user.id))
            )


# Module instance
registration_module = RegistrationModule()
