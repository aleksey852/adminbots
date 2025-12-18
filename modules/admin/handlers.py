"""
Admin Module - Admin tools and statistics
"""
import functools
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
import orjson
import logging
import csv
import os
import tempfile
import time
import uuid

from modules.base import BotModule
from utils.states import AdminBroadcast, AdminRaffle, AdminManualReceipt
from .keyboards import (
    get_confirm_keyboard, get_schedule_keyboard, get_admin_broadcast_preview_keyboard
)
from modules.core.keyboards import get_main_keyboard, get_cancel_keyboard
from database.bot_methods import (
    add_campaign, get_stats, get_participants_count, get_user_wins,
    add_receipt, get_user_by_id, get_total_users_count, search_users,
    get_recent_raffles_with_winners, get_all_winners_for_export,
    add_manual_tickets
)
from utils.config_manager import config_manager
from bot_manager import bot_manager
import config

logger = logging.getLogger(__name__)

class AdminModule(BotModule):
    """Admin functionality for bot management"""
    
    name = "admin"
    version = "1.0.0"
    description = "Инструменты администратора: рассылки, розыгрыши, статистика"
    default_enabled = True
    
    def _setup_handlers(self):
        """Setup admin handlers"""
        
        @self.router.message(F.text == "📊 Статистика")
        async def show_stats_handler(message: Message, bot_id: int = None):
            if not bot_id or not config.is_admin(message.from_user.id): return
            
            stats = await get_stats()
            participants = await get_participants_count()
            conversion = (participants / stats['total_users'] * 100) if stats['total_users'] else 0
            
            stats_msg = config_manager.get_message(
                'stats_msg', 
                "📊 Статистика\n\n👥 Пользователи: {users} (+{users_today})\n🧾 Чеки: {receipts} (принято: {valid}) (+{receipts_today})\n🎯 Участников: {participants}\n📈 Конверсия: {conversion:.1f}%\n🏆 Победителей: {winners}",
                bot_id=bot_id
            ).format(
                users=stats['total_users'], 
                users_today=stats['users_today'], 
                receipts=stats['total_receipts'], 
                valid=stats['valid_receipts'], 
                receipts_today=stats['receipts_today'], 
                participants=participants, 
                conversion=conversion, 
                winners=stats['total_winners']
            )
            await message.answer(stats_msg)

        @self.router.message(F.text == "📢 Рассылка")
        async def start_broadcast(message: Message, state: FSMContext, bot_id: int = None):
            if not bot_id or not config.is_admin(message.from_user.id): return
            
            total = await get_total_users_count()
            await message.answer(f"📢 Рассылка\n\nПолучателей: {total}\n\nОтправьте сообщение:", reply_markup=get_cancel_keyboard())
            await state.set_state(AdminBroadcast.content)

        @self.router.message(AdminBroadcast.content)
        async def process_broadcast_content(message: Message, state: FSMContext, bot: Bot, bot_id: int = None):
            if not config.is_admin(message.from_user.id):
                await state.clear()
                return
            
            if message.text == "❌ Отмена":
                await state.clear()
                await message.answer("Отменено", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            
            content = {"photo": message.photo[-1].file_id, "caption": message.caption} if message.photo else {"text": message.text}
            
            if not content.get("text") and not content.get("photo"):
                await message.answer("Отправьте текст или фото")
                return
            
            await state.update_data(content=content)
            await message.answer("👀 Предпросмотр:")
            
            if "photo" in content:
                await bot.send_photo(message.from_user.id, content["photo"], caption=content.get("caption"))
            else:
                await message.answer(content.get("text", ""))
            
            await message.answer("Всё верно?", reply_markup=get_admin_broadcast_preview_keyboard())
            await state.set_state(AdminBroadcast.preview)

        @self.router.callback_query(AdminBroadcast.preview)
        async def broadcast_preview_callback(callback: CallbackQuery, state: FSMContext, bot_id: int = None):
            if not config.is_admin(callback.from_user.id): return
            
            if callback.data == "broadcast_edit":
                await callback.message.answer("Отправьте новое сообщение:", reply_markup=get_cancel_keyboard())
                await state.set_state(AdminBroadcast.content)
            elif callback.data == "broadcast_cancel":
                await state.clear()
                await callback.message.answer("Отменено", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
            elif callback.data == "broadcast_send":
                await callback.message.answer("⏰ Когда?\n\n2025-01-15 18:00\n\nИли «Сейчас»", reply_markup=get_schedule_keyboard())
                await state.set_state(AdminBroadcast.schedule)
            await callback.answer()

        @self.router.message(AdminBroadcast.schedule)
        async def process_broadcast_schedule(message: Message, state: FSMContext, bot_id: int = None):
            if not bot_id or not config.is_admin(message.from_user.id): return
            
            if message.text == "❌ Отмена":
                await state.clear()
                await message.answer("Отменено", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            
            data = await state.get_data()
            scheduled_for = None
            if message.text != "🚀 Сейчас":
                dt = config.parse_scheduled_time(message.text)
                if not dt or dt < config.get_now().replace(tzinfo=None):
                    await message.answer("Неверная дата. Формат: 2025-01-15 18:00")
                    return
                scheduled_for = dt
            
            campaign_id = await add_campaign("broadcast", data["content"], scheduled_for)
            msg = f"✅ Рассылка #{campaign_id} " + (f"запланирована на {message.text}" if scheduled_for else "начнётся скоро")
            
            await message.answer(msg, reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
            await state.clear()

        @self.router.message(F.text == "🎁 Розыгрыш")
        async def start_raffle(message: Message, state: FSMContext, bot_id: int = None):
            if not bot_id or not config.is_admin(message.from_user.id): return
            
            participants = await get_participants_count()
            if participants == 0:
                await message.answer("Нет участников", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            
            await message.answer(f"🎁 Розыгрыш\nУчастников: {participants}\n\nНазвание приза:", reply_markup=get_cancel_keyboard())
            await state.set_state(AdminRaffle.prize_name)

        @self.router.message(AdminRaffle.prize_name)
        async def raffle_prize(message: Message, state: FSMContext, bot_id: int = None):
            if message.text == "❌ Отмена":
                await state.clear()
                await message.answer("Отменено", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            await state.update_data(prize=message.text)
            await message.answer("Сколько победителей?")
            await state.set_state(AdminRaffle.winner_count)

        @self.router.message(AdminRaffle.winner_count)
        async def raffle_count(message: Message, state: FSMContext, bot_id: int = None):
            if not bot_id:
                await state.clear()
                return
            if not message.text or not message.text.isdigit():
                await message.answer("Введите число")
                return
            
            count = int(message.text)
            participants = await get_participants_count()
            
            if count < 1 or count > participants:
                await message.answer(f"От 1 до {participants}")
                return
            
            await state.update_data(count=count)
            await message.answer("📨 Сообщение для ПОБЕДИТЕЛЕЙ:")
            await state.set_state(AdminRaffle.winner_message)

        @self.router.message(AdminRaffle.winner_message)
        async def raffle_win_msg(message: Message, state: FSMContext):
            content = {"photo": message.photo[-1].file_id, "caption": message.caption} if message.photo else {"text": message.text}
            await state.update_data(win_msg=content)
            await message.answer("📨 Сообщение для ОСТАЛЬНЫХ:")
            await state.set_state(AdminRaffle.loser_message)

        @self.router.message(AdminRaffle.loser_message)
        async def raffle_lose_msg(message: Message, state: FSMContext):
            content = {"photo": message.photo[-1].file_id, "caption": message.caption} if message.photo else {"text": message.text}
            await state.update_data(lose_msg=content)
            await message.answer("⏰ Когда?\n\n2025-01-15 18:00 или «Сейчас»", reply_markup=get_schedule_keyboard())
            await state.set_state(AdminRaffle.schedule)

        @self.router.message(AdminRaffle.schedule)
        async def raffle_schedule(message: Message, state: FSMContext, bot_id: int = None):
            if message.text == "❌ Отмена":
                await state.clear()
                await message.answer("Отменено", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            
            scheduled_for = None
            if message.text != "🚀 Сейчас":
                dt = config.parse_scheduled_time(message.text)
                if not dt or dt < config.get_now().replace(tzinfo=None):
                    await message.answer("Неверная дата")
                    return
                scheduled_for = dt
            
            await state.update_data(scheduled_for=scheduled_for, schedule_text=message.text)
            data = await state.get_data()
            await message.answer(f"⚠️ Подтверждение\n\nПриз: {data['prize']}\nПобедителей: {data['count']}\nВремя: {message.text}\n\nПодтвердить?", reply_markup=get_confirm_keyboard())
            await state.set_state(AdminRaffle.confirm)

        @self.router.message(AdminRaffle.confirm)
        async def raffle_confirm(message: Message, state: FSMContext, bot_id: int = None):
            if message.text != "✅ Подтвердить":
                await state.clear()
                await message.answer("Отменено", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            
            data = await state.get_data()
            campaign_id = await add_campaign(
                "raffle", 
                {
                    "prize": data["prize"], 
                    "count": data["count"], 
                    "win_msg": data["win_msg"], 
                    "lose_msg": data["lose_msg"],
                    "is_final": False # Regular raffle by default
                }, 
                data.get("scheduled_for")
            )
            await message.answer(f"✅ Розыгрыш #{campaign_id} начнётся скоро", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
            await state.clear()

        @self.router.message(F.text == "🏆 Победители")
        async def show_winners(message: Message, bot_id: int = None):
            if not bot_id or not config.is_admin(message.from_user.id): return
            
            campaigns = await get_recent_raffles_with_winners(limit=5)
            if not campaigns:
                await message.answer("Розыгрышей ещё не было")
                return
            
            text = ["🏆 Последние розыгрыши\n"]
            for c in campaigns:
                content = c['content'] if isinstance(c['content'], dict) else orjson.loads(c['content'])
                text.append(f"\n🎁 {content.get('prize', 'Приз')}\n📅 {str(c['completed_at'])[:16]}\n👥 {len(c['winners'])}\n")
                for w in c['winners'][:5]: 
                    text.append(f"  {'✓' if w['notified'] else '..'} {w.get('full_name', 'Unknown')}\n")
            await message.answer("".join(text))

        @self.router.message(F.text == "📥 Экспорт победителей")
        async def export_winners_handler(message: Message, bot_id: int = None):
            if not bot_id or not config.is_admin(message.from_user.id): return
            
            winners = await get_all_winners_for_export()
            if not winners:
                await message.answer("Победителей нет")
                return
            
            fd, path = tempfile.mkstemp(suffix=".csv")
            try:
                with os.fdopen(fd, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Имя", "Телефон", "Username", "Приз", "Дата"])
                    for w in winners: 
                        writer.writerow([
                            w.get('full_name', ''), 
                            w.get('phone', ''), 
                            f"@{w.get('username', '')}", 
                            w.get('prize_name', ''), 
                            str(w.get('created_at', ''))[:19]
                        ])
                await message.answer_document(FSInputFile(path, filename="winners.csv"), caption=f"📥 {len(winners)} победителей")
            finally:
                if os.path.exists(path): os.remove(path)

        @self.router.message(F.text == "➕ Ручное добавление")
        async def start_manual_receipt(message: Message, state: FSMContext, bot_id: int = None):
            if not bot_id or not config.is_admin(message.from_user.id): return
            
            await message.answer("➕ Введите пользователя (ID, @username или телефон):", reply_markup=get_cancel_keyboard())
            await state.set_state(AdminManualReceipt.user_id)

        @self.router.message(AdminManualReceipt.user_id)
        async def process_manual_user(message: Message, state: FSMContext, bot_id: int = None):
            if message.text == "❌ Отмена":
                await state.clear()
                await message.answer("Отменено", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            
            users = await search_users(message.text.strip())
            
            # Helper to find user by ID if digit
            user = None
            if users:
                user = users[0]
            elif message.text.isdigit():
                user = await get_user_by_id(int(message.text))
                
            if not user:
                await message.answer("❌ Пользователь не найден", reply_markup=get_cancel_keyboard())
                return
            
            await state.update_data(user_id=user['id'], user_name=user['full_name'])
            await message.answer(f"Выбран: {user['full_name']}\n\n🎟 Сколько билетов начислить?", reply_markup=get_cancel_keyboard())
            await state.set_state(AdminManualReceipt.tickets)

        @self.router.message(AdminManualReceipt.tickets)
        async def process_manual_tickets(message: Message, state: FSMContext, bot_id: int = None):
            if message.text == "❌ Отмена":
                await state.clear()
                await message.answer("Отменено", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
                
            if not message.text.isdigit():
                 await message.answer("Введите число")
                 return
                 
            count = int(message.text)
            if count < 1:
                await message.answer("Минимум 1 билет")
                return
            
            await state.update_data(tickets=count)
            data = await state.get_data()
            
            await message.answer(f"⚠️ Начислить {count} билетов пользователю {data['user_name']}?", reply_markup=get_confirm_keyboard())
            await state.set_state(AdminManualReceipt.confirm)

        @self.router.message(AdminManualReceipt.confirm)
        async def confirm_manual_receipt(message: Message, state: FSMContext, bot_id: int = None):
            if message.text != "✅ Подтвердить":
                await state.clear()
                await message.answer("Отменено", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
                return
            
            data = await state.get_data()
            
            # Use specific manual tickets method
            await add_manual_tickets(
                user_id=data['user_id'], 
                tickets=data['tickets'], 
                reason="Admin Manual Addition", 
                created_by=f"Admin {message.from_user.id}"
            )
            
            await message.answer(f"✅ Успешно начислено {data['tickets']} билетов!", reply_markup=get_main_keyboard(True, bot_manager.bot_types.get(bot_id, 'receipt')))
            await state.clear()

# Module instance
admin_module = AdminModule()
