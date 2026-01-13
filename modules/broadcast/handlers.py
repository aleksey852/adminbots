"""
Broadcast Module - Send messages to users
"""
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from core.module_base import BotModule
from utils.config_manager import config_manager
from modules.core.keyboards import get_main_keyboard, get_cancel_keyboard
from database.bot_methods import get_total_users_count, add_campaign
from bot_manager import bot_manager
import config

logger = logging.getLogger(__name__)


class BroadcastStates(StatesGroup):
    """Broadcast creation states"""
    content = State()
    preview = State()
    schedule = State()


class BroadcastModule(BotModule):
    """Broadcast messages to users"""
    
    name = "broadcast"
    version = "1.0.0"
    description = "Рассылка сообщений пользователям"
    default_enabled = True
    dependencies = ["core"]
    
    # State protection
    states = ["BroadcastStates:content", "BroadcastStates:preview", "BroadcastStates:schedule"]
    state_timeout = 1800  # 30 min for composing
    
    default_messages = {
        "broadcast_start": "📢 Рассылка\n\nПолучателей: {count}\n\nОтправьте сообщение (текст или фото):",
        "broadcast_preview": "👀 Предпросмотр:",
        "broadcast_confirm": "Всё верно?",
        "broadcast_schedule": "⏰ Когда отправить?\n\nФормат: 2025-01-15 18:00\nИли нажмите «Сейчас»",
        "broadcast_scheduled": "✅ Рассылка #{id} запланирована на {time}",
        "broadcast_started": "✅ Рассылка #{id} начнётся скоро",
        "broadcast_cancelled": "❌ Рассылка отменена",
        "invalid_date": "❌ Неверная дата. Формат: 2025-01-15 18:00",
    }
    
    def _setup_handlers(self):
        """Setup broadcast handlers (admin only via bot command)"""
        
        from aiogram.filters import Command
        
        @self.router.message(Command("broadcast"))
        async def start_broadcast_command(message: Message, state: FSMContext, bot_id: int = None):
            """Start broadcast via /broadcast command (admin only)"""
            if not bot_id or not config.is_admin(message.from_user.id):
                return
            
            total = await get_total_users_count()
            msg = config_manager.get_message(
                'broadcast_start', 
                self.default_messages['broadcast_start'], 
                bot_id=bot_id
            ).format(count=total)
            
            await message.answer(msg, reply_markup=get_cancel_keyboard())
            await state.set_state(BroadcastStates.content)
            await state.update_data(bot_id=bot_id)
        
        @self.router.message(BroadcastStates.content)
        async def process_content(message: Message, state: FSMContext, bot: Bot, bot_id: int = None):
            if not config.is_admin(message.from_user.id):
                await state.clear()
                return
            
            if message.text == "❌ Отмена":
                await state.clear()
                msg = config_manager.get_message('broadcast_cancelled', self.default_messages['broadcast_cancelled'], bot_id=bot_id)
                await message.answer(msg, reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            
            # Save content
            content = {}
            if message.photo:
                content = {"photo": message.photo[-1].file_id, "caption": message.caption}
            elif message.video:
                content = {"video": message.video.file_id, "caption": message.caption}
            elif message.text:
                content = {"text": message.text}
            
            if not content:
                await message.answer("Отправьте текст, фото или видео")
                return
            
            await state.update_data(content=content)
            
            # Show preview
            preview_msg = config_manager.get_message('broadcast_preview', self.default_messages['broadcast_preview'], bot_id=bot_id)
            await message.answer(preview_msg)
            
            if "photo" in content:
                await bot.send_photo(message.from_user.id, content["photo"], caption=content.get("caption"))
            elif "video" in content:
                await bot.send_video(message.from_user.id, content["video"], caption=content.get("caption"))
            else:
                await message.answer(content.get("text", ""))
            
            # Confirm buttons
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_send")],
                [InlineKeyboardButton(text="✏️ Изменить", callback_data="broadcast_edit")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
            ])
            
            confirm_msg = config_manager.get_message('broadcast_confirm', self.default_messages['broadcast_confirm'], bot_id=bot_id)
            await message.answer(confirm_msg, reply_markup=kb)
            await state.set_state(BroadcastStates.preview)
        
        @self.router.callback_query(BroadcastStates.preview)
        async def process_preview(callback: CallbackQuery, state: FSMContext, bot_id: int = None):
            if not config.is_admin(callback.from_user.id):
                return
            
            action = callback.data
            
            if action == "broadcast_cancel":
                await state.clear()
                msg = config_manager.get_message('broadcast_cancelled', self.default_messages['broadcast_cancelled'], bot_id=bot_id)
                await callback.message.answer(msg, reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                await callback.answer()
                return
            
            if action == "broadcast_edit":
                msg = config_manager.get_message('broadcast_start', self.default_messages['broadcast_start'], bot_id=bot_id)
                total = await get_total_users_count()
                await callback.message.answer(msg.format(count=total), reply_markup=get_cancel_keyboard())
                await state.set_state(BroadcastStates.content)
                await callback.answer()
                return
            
            if action == "broadcast_send":
                # Schedule options
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 Сейчас", callback_data="schedule_now")],
                ])
                
                schedule_msg = config_manager.get_message('broadcast_schedule', self.default_messages['broadcast_schedule'], bot_id=bot_id)
                await callback.message.answer(schedule_msg, reply_markup=kb)
                await state.set_state(BroadcastStates.schedule)
                await callback.answer()
        
        @self.router.callback_query(BroadcastStates.schedule, F.data == "schedule_now")
        async def schedule_now(callback: CallbackQuery, state: FSMContext, bot_id: int = None):
            if not config.is_admin(callback.from_user.id):
                return
            
            data = await state.get_data()
            campaign_id = await add_campaign("broadcast", data["content"], None)
            
            msg = config_manager.get_message(
                'broadcast_started', 
                self.default_messages['broadcast_started'], 
                bot_id=bot_id
            ).format(id=campaign_id)
            
            await callback.message.answer(msg, reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
            await state.clear()
            await callback.answer()
        
        @self.router.message(BroadcastStates.schedule)
        async def schedule_datetime(message: Message, state: FSMContext, bot_id: int = None):
            if not config.is_admin(message.from_user.id):
                await state.clear()
                return
            
            if message.text == "❌ Отмена":
                await state.clear()
                msg = config_manager.get_message('broadcast_cancelled', self.default_messages['broadcast_cancelled'], bot_id=bot_id)
                await message.answer(msg, reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            
            # Parse datetime
            dt = config.parse_scheduled_time(message.text)
            if not dt or dt < config.get_now().replace(tzinfo=None):
                msg = config_manager.get_message('invalid_date', self.default_messages['invalid_date'], bot_id=bot_id)
                await message.answer(msg)
                return
            
            data = await state.get_data()
            campaign_id = await add_campaign("broadcast", data["content"], dt)
            
            msg = config_manager.get_message(
                'broadcast_scheduled', 
                self.default_messages['broadcast_scheduled'], 
                bot_id=bot_id
            ).format(id=campaign_id, time=message.text)
            
            await message.answer(msg, reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
            await state.clear()


# Module instance
broadcast_module = BroadcastModule()
