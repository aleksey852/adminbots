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
from utils.subscription import check_subscription, get_subscription_keyboard
from bot_manager import bot_manager
import config

logger = logging.getLogger(__name__)

class RegistrationModule(BotModule):
    """User registration module with optional subscription requirement"""
    
    name = "registration"
    version = "2.0.0"
    description = "Модуль регистрации пользователей"
    default_enabled = True
    
    # Subscription settings integrated into registration
    settings_schema = {
        "subscription_required": {
            "type": "checkbox",
            "label": "Требовать подписку на канал",
            "default": "false",
            "required": False,
            "group": "Подписка"
        },
        "subscription_channel_id": {
            "type": "text",
            "label": "ID канала (напр. -100...)",
            "default": "",
            "required": False,
            "group": "Подписка"
        },
        "subscription_channel_url": {
            "type": "text",
            "label": "Ссылка на канал",
            "default": "",
            "required": False,
            "group": "Подписка"
        }
    }
    
    default_messages = {
        "reg_cancel": "Хорошо! Возвращайтесь 👋",
        "reg_name_error": "Введите имя (2-100 символов)",
        "reg_phone_prompt": "Отлично, {name}! 👋\n\nОтправьте номер телефона:",
        "reg_phone_error": "❌ Неверный формат. Введите в международном формате, например +79991234567",
        "reg_phone_request": "Отправьте номер телефона",
        "reg_success": "✅ Регистрация завершена!",
        "reg_success_promo": "✅ Регистрация завершена!\n\nОтправьте промокод сообщением в этот чат.\n\nАкция: {start} — {end}\n\n👇 Введите промокод",
        "sub_warning": "⚠️ Для участия в акции необходимо подписаться на наш канал!",
    }
    
    # E.164-ish validator
    # Allows + (optional) followed by 10-15 digits
    PHONE_PATTERN = re.compile(r'^\+?[1-9]\d{9,14}$')
    
    
    def _setup_handlers(self):
        """Setup registration handlers - fixed flow: name -> phone -> done"""
        
        @self.router.message(Registration.name)
        async def process_name(message: Message, state: FSMContext, bot_id: int = None):
            is_sub, _, channel_url = await check_subscription(message.from_user.id, message.bot, bot_id)
            if not is_sub:
                msg = config_manager.get_message('sub_warning', self.default_messages['sub_warning'], bot_id=bot_id)
                await message.answer(msg, reply_markup=get_subscription_keyboard(channel_url))
                return

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
                # 1. Strip whitespace and separators
                text = message.text.strip()
                clean = re.sub(r'[\s\-\(\)]', '', text)
                
                # 2. Handle Russian 8 prefix logic
                # Only if starts with 8 and is 11 digits total (e.g., 89991234567)
                if len(clean) == 11 and clean.startswith('8'):
                     clean = '7' + clean[1:]
                
                # 3. Final Validation: must be digits (after stripping +)
                digits_only = clean[1:] if clean.startswith('+') else clean
                
                if not digits_only.isdigit() or len(digits_only) < 10 or len(digits_only) > 15:
                    msg = config_manager.get_message('reg_phone_error', self.default_messages['reg_phone_error'], bot_id=bot_id)
                    await message.answer(msg)
                    return

                phone = clean if clean.startswith('+') else '+' + clean
            else:
                msg = config_manager.get_message('reg_phone_request', self.default_messages['reg_phone_request'], bot_id=bot_id)
                await message.answer(msg)
                return
            
            
            data = await state.get_data()
            await add_user(
                message.from_user.id,
                message.from_user.username or "",
                data.get("name", "Пользователь"),
                phone
            )
            
            # Registration complete
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

