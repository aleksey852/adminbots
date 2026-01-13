"""
Profile Module - User profile viewing and editing
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from core.module_base import BotModule
from database.bot_methods import get_user_with_stats, update_user_field
from utils.config_manager import config_manager
from modules.core.keyboards import get_main_keyboard
from bot_manager import bot_manager
import config

logger = logging.getLogger(__name__)


class ProfileStates(StatesGroup):
    """Profile editing states"""
    editing_name = State()
    editing_phone = State()
    editing_email = State()


class ProfileModule(BotModule):
    """User profile viewing and editing module"""
    
    name = "profile"
    version = "1.0.0"
    description = "Просмотр и редактирование профиля пользователя"
    default_enabled = True
    dependencies = ["core"]
    
    # Menu button
    menu_buttons = [
        {"text": "👤 Профиль", "order": 50}
    ]
    
    # State protection
    states = ["ProfileStates:editing_name", "ProfileStates:editing_phone", "ProfileStates:editing_email"]
    state_timeout = 600
    
    settings_schema = {
        "fields": {
            "type": "text",
            "label": "Поля профиля (через запятую)",
            "default": "name,phone,email",
            "required": False
        },
        "required_fields": {
            "type": "text",
            "label": "Обязательные поля",
            "default": "",
            "required": False,
            "help": "Без этих полей нельзя активировать коды/чеки (phone, email)"
        }
    }
    
    default_messages = {
        "profile_view": "👤 Ваш профиль\n\n📛 Имя: {name}\n📱 Телефон: {phone}\n📧 Email: {email}",
        "profile_edit_prompt": "Нажмите на поле для редактирования:",
        "edit_name_prompt": "📛 Введите новое имя:",
        "edit_phone_prompt": "📱 Введите номер телефона:",
        "edit_email_prompt": "📧 Введите email:",
        "field_updated": "✅ {field} обновлено!",
        "required_missing": "⚠️ Для продолжения укажите {field}",
        "cancel": "❌ Отменено",
    }
    
    def _setup_handlers(self):
        """Setup profile handlers"""
        
        @self.router.message(F.text == "👤 Профиль")
        async def show_profile(message: Message, bot_id: int = None):
            if not bot_id:
                return
                
            user = await get_user_with_stats(message.from_user.id)
            if not user:
                await message.answer("Вы не зарегистрированы. Нажмите /start")
                return
            
            # Get fields to show
            settings = await self.get_settings(bot_id)
            fields = [f.strip() for f in settings.get('fields', 'name,phone,email').split(',')]
            
            # Build profile text
            profile_text = "👤 Ваш профиль\n\n"
            
            if 'name' in fields:
                profile_text += f"📛 Имя: {user.get('full_name', 'не указано')}\n"
            if 'phone' in fields:
                phone = user.get('phone') or 'не указан'
                profile_text += f"📱 Телефон: {phone}\n"
            if 'email' in fields:
                email = user.get('email') or 'не указан'
                profile_text += f"📧 Email: {email}\n"
            
            # Build edit keyboard
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            buttons = []
            if 'name' in fields:
                buttons.append([InlineKeyboardButton(text="📛 Изменить имя", callback_data="profile_edit_name")])
            if 'phone' in fields:
                buttons.append([InlineKeyboardButton(text="📱 Изменить телефон", callback_data="profile_edit_phone")])
            if 'email' in fields:
                buttons.append([InlineKeyboardButton(text="📧 Изменить email", callback_data="profile_edit_email")])
            
            kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
            await message.answer(profile_text, reply_markup=kb)
        
        @self.router.callback_query(F.data.startswith("profile_edit_"))
        async def start_edit(callback: CallbackQuery, state: FSMContext, bot_id: int = None):
            field = callback.data.replace("profile_edit_", "")
            
            prompts = {
                "name": ("edit_name_prompt", ProfileStates.editing_name),
                "phone": ("edit_phone_prompt", ProfileStates.editing_phone),
                "email": ("edit_email_prompt", ProfileStates.editing_email),
            }
            
            if field not in prompts:
                await callback.answer("Неизвестное поле")
                return
            
            prompt_key, state_to_set = prompts[field]
            prompt = config_manager.get_message(prompt_key, self.default_messages[prompt_key], bot_id=bot_id)
            
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="profile_cancel")]
            ])
            
            await callback.message.answer(prompt, reply_markup=cancel_kb)
            await state.set_state(state_to_set)
            await state.update_data(field=field, bot_id=bot_id)
            await callback.answer()
        
        @self.router.callback_query(F.data == "profile_cancel")
        async def cancel_edit(callback: CallbackQuery, state: FSMContext, bot_id: int = None):
            await state.clear()
            await callback.message.edit_text(
                config_manager.get_message('cancel', self.default_messages['cancel'], bot_id=bot_id)
            )
            await callback.answer()
        
        @self.router.message(ProfileStates.editing_name)
        @self.router.message(ProfileStates.editing_phone)
        @self.router.message(ProfileStates.editing_email)
        async def process_edit(message: Message, state: FSMContext, bot_id: int = None):
            data = await state.get_data()
            field = data.get('field')
            
            if not field or not message.text:
                await state.clear()
                return
            
            # Basic validation
            value = message.text.strip()
            
            if field == 'name' and (len(value) < 2 or len(value) > 100):
                await message.answer("Имя должно быть от 2 до 100 символов")
                return
            
            if field == 'phone':
                import re
                clean = re.sub(r'[\s\-\(\)]', '', value)
                if len(clean) == 11 and clean.startswith('8'):
                    clean = '7' + clean[1:]
                if not clean.startswith('+'):
                    clean = '+' + clean
                digits = clean[1:] if clean.startswith('+') else clean
                if not digits.isdigit() or len(digits) < 10 or len(digits) > 15:
                    await message.answer("Неверный формат телефона")
                    return
                value = clean
            
            if field == 'email' and '@' not in value:
                await message.answer("Неверный формат email")
                return
            
            # Update in database
            user = await get_user_with_stats(message.from_user.id)
            if user:
                db_field = 'full_name' if field == 'name' else field
                await update_user_field(user['id'], db_field, value)
            
            await state.clear()
            
            field_names = {'name': 'Имя', 'phone': 'Телефон', 'email': 'Email'}
            msg = config_manager.get_message('field_updated', self.default_messages['field_updated'], bot_id=bot_id)
            await message.answer(msg.format(field=field_names.get(field, field)))
            
            # Show updated profile
            await show_profile(message, bot_id)
    
    async def check_required(self, user_id: int, bot_id: int) -> bool:
        """Check if user has all required fields filled."""
        settings = await self.get_settings(bot_id)
        required = [f.strip() for f in settings.get('required_fields', '').split(',') if f.strip()]
        
        if not required:
            return True
        
        user = await get_user_with_stats(user_id)
        if not user:
            return False
        
        for field in required:
            db_field = 'full_name' if field == 'name' else field
            if not user.get(db_field):
                return False
        
        return True
    
    async def request_required_fields(self, message: Message, bot_id: int):
        """Ask user to fill required fields."""
        settings = await self.get_settings(bot_id)
        required = [f.strip() for f in settings.get('required_fields', '').split(',') if f.strip()]
        
        user = await get_user_with_stats(message.from_user.id)
        if not user:
            return
        
        missing = []
        field_names = {'name': 'имя', 'phone': 'телефон', 'email': 'email'}
        
        for field in required:
            db_field = 'full_name' if field == 'name' else field
            if not user.get(db_field):
                missing.append(field_names.get(field, field))
        
        if missing:
            msg = config_manager.get_message(
                'required_missing', 
                self.default_messages['required_missing'], 
                bot_id=bot_id
            ).format(field=', '.join(missing))
            
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            buttons = []
            for field in required:
                db_field = 'full_name' if field == 'name' else field
                if not user.get(db_field):
                    buttons.append([InlineKeyboardButton(
                        text=f"📝 Указать {field_names.get(field, field)}", 
                        callback_data=f"profile_edit_{field}"
                    )])
            
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer(msg, reply_markup=kb)


# Module instance
profile_module = ProfileModule()
