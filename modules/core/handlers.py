"""
Core Module - Base bot navigation and user profile
"""
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
import math
import logging

from core.module_base import BotModule
from database.bot_methods import get_user_with_stats, get_user_receipts, update_username, get_user_wins
from utils.config_manager import config_manager
from bot_manager import bot_manager
from .keyboards import (
    get_main_keyboard, get_cancel_keyboard, get_receipts_pagination_keyboard,
    get_faq_keyboard, get_faq_back_keyboard, get_support_keyboard
)
from utils.subscription import check_subscription, get_subscription_keyboard
import config

logger = logging.getLogger(__name__)

class CoreModule(BotModule):
    """Base bot functionality: start, menu, profile, FAQ, support"""
    
    name = "core"
    version = "2.0.0"
    description = "Базовый функционал: меню, профиль, FAQ"
    default_enabled = True
    
    # State protection
    states = []  # Core has no waiting states
    state_timeout = 600
    
    settings_schema = {
        "promo_start_date": {
            "type": "date",
            "label": "Дата начала акции",
            "default": str(config.PROMO_START_DATE),
            "required": True
        },
        "promo_end_date": {
            "type": "date",
            "label": "Дата окончания акции",
            "default": str(config.PROMO_END_DATE),
            "required": True
        }
    }
    
    RECEIPTS_PER_PAGE = 10
    
    default_messages = {
        # === ОСНОВНЫЕ ===
        "cancel_msg": "Выбери действие 👇\n🎫 Билетов: {count}",
        "welcome_back": "Привет, {name}! 👋\n\n🎫 У тебя {count} билетов{days_text}\n🏆 Чем больше — тем выше шанс!\n\n👇 Введи ещё один код:",
        "welcome_new": "🎉 Привет!\n\nДля участия введи своё имя:",
        "not_registered": "Сначала /start",
        "status": "📊 {name}\n\n🎫 Билетов: {tickets}\n⏳ До конца: {days} дн.",
        
        # === ИСТОРИЯ ===
        "no_receipts_promo": "📋 Пока нет активаций\n\n💡 Введи промокод — получи билет!",
        "no_receipts_receipt": "📋 Пока нет чеков\n\n💡 Загрузи QR-код — получи билеты!",
        "receipts_list_promo": "📋 Твои активации ({total})\n",
        "receipts_list_receipt": "📋 Твои чеки ({total})\n",
        
        # === ПРОФИЛЬ ===
        "profile_promo": "👤 Твой профиль\n\n📛 {name}\n📱 {phone}\n\n📊 Активаций: {total}\n🎫 Билетов: {tickets}{wins_text}{days_text}",
        "profile_receipt": "👤 Твой профиль\n\n📛 {name}\n📱 {phone}\n\n🧾 Чеков: {total}\n🎫 Билетов: {tickets}{wins_text}{days_text}",
        
        # === FAQ ===
        "faq_title": "❓ Выбери тему:",
        "support_msg": "🆘 Нужна помощь?\n\nНапиши нам!",
        "help_promo": "🤖 Что умеет бот:\n\n🎁 Ввести промокод\n🎫 Мои билеты\n👤 Профиль\nℹ️ Помощь",
        "help_receipt": "🤖 Что умеет бот:\n\n🧾 Загрузить чек\n🎫 Мои билеты\n👤 Профиль\nℹ️ Помощь",
        
        # === ОШИБКИ ===
        "error_init": "⚠️ Ошибка. Попробуй /start",
        "error_auth": "⚠️ Ты не зарегистрирован. Нажми /start",
        
        # === БИЛЕТЫ ===
        "tickets_info": "🎫 ТВОИ БИЛЕТЫ\n═══════════════════\n\n{content}",
        "tickets_empty_promo": "📭 Пока нет билетов\n\n💡 Введи промокод — получи билет!\n\n1 код = 1 билет 🎟",
        "tickets_empty_receipt": "📭 Пока нет билетов\n\n💡 Загрузи чек — получи билеты!",
        "tickets_mechanics_promo": "\n─────────────────────\nℹ️ КАК РАБОТАЮТ БИЛЕТЫ\n\n🎁 1 промокод = 1 билет\n🏆 Чем больше — тем выше шанс!",
        "tickets_mechanics_receipt": "\n─────────────────────\nℹ️ КАК РАБОТАЮТ БИЛЕТЫ\n\n🧾 1 чек = 1+ билетов\n🏆 Чем больше — тем выше шанс!",
        
        # === FAQ ДЕТАЛИ ===
        "faq_how_promo": "🎯 Как участвовать?\n\n1️⃣ Найди промокод на упаковке\n2️⃣ Отправь его сюда\n3️⃣ Получи билет!\n\n💡 Больше билетов = выше шанс!",
        "faq_how_receipt": "🎯 Как участвовать?\n\n1️⃣ Купи акционный товар\n2️⃣ Сфотографируй QR-код чека\n3️⃣ Отправь фото сюда\n4️⃣ Получи билеты!\n\n💡 Больше билетов = выше шанс!",
        "faq_limit_promo": "🔢 Сколько кодов можно?\n\nБез ограничений! 🎉\n\n1 код = 1 билет\nКопи билеты для розыгрыша!",
        "faq_limit_receipt": "🧾 Сколько чеков можно?\n\nБез ограничений! 🎉\n\n1 чек = 1+ билетов\nКопи билеты для розыгрыша!",
        "faq_win": "🏆 Как узнать о выигрыше?\n\nПришлём сообщение сюда сразу после розыгрыша!",
        "faq_reject_promo": "❌ Код не принят?\n\n• Опечатка в коде\n• Код уже использован\n\n💡 Проверь и попробуй ещё раз",
        "faq_reject_receipt": "❌ Чек не принят?\n\n• QR-код нечёткий\n• Нет акционных товаров\n• Чек уже загружен\n\n💡 Сделай чёткое фото",
        "faq_dates": "📅 Сроки акции\n\n🟢 Начало: {start}\n🔴 Окончание: {end}",
        "faq_prizes": "🎁 Призы\n\nПризы определяются в каждом розыгрыше.\n🏆 Чем больше билетов — тем выше шанс!",
        "faq_raffle": "🎲 Как работают розыгрыши?\n\n🎫 Билеты копятся за всё время\n🏆 Розыгрыши проводит администратор\n📢 Сообщим тебе в этом боте!",
        
        # === ПОДПИСКА ===
        "sub_check_success": "✅ Подписка подтверждена!",
        "sub_check_fail": "❌ Ты ещё не подписан на канал!",
        "sub_warning": "⚠️ Для участия подпишись на наш канал!",
    }
    
    def _setup_handlers(self):
        """Setup core handlers"""
        
        @self.router.message(Command("cancel"))
        @self.router.message(F.text == "❌ Отмена")
        async def cancel_handler(message: Message, state: FSMContext, bot_id: int = None):
            await state.clear()
            
            count = 0
            if bot_id:
                user = await get_user_with_stats(message.from_user.id)
                if user:
                    count = user.get('total_tickets') or user.get('valid_receipts') or 0
            
            cancel_msg = config_manager.get_message(
                'cancel_msg',
                self.default_messages['cancel_msg'],
                bot_id=bot_id
            ).format(count=count)
            
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            await message.answer(
                cancel_msg,
                reply_markup=get_main_keyboard(config.is_admin(message.from_user.id), bot_type)
            )

        @self.router.message(F.text == "🏠 В меню")
        async def go_to_menu(message: Message, state: FSMContext, bot_id: int = None):
            await cancel_handler(message, state, bot_id)

        @self.router.message(CommandStart())
        async def command_start(message: Message, state: FSMContext, bot_id: int = None):
            if not bot_id:
                await message.answer(config_manager.get_message('error_init', self.default_messages['error_init'], bot_id=bot_id))
                return
            
            # Check subscription
            is_sub, _, channel_url = await check_subscription(message.from_user.id, message.bot, bot_id)
            if not is_sub:
                msg = config_manager.get_message('sub_warning', self.default_messages['sub_warning'], bot_id=bot_id)
                await message.answer(msg, reply_markup=get_subscription_keyboard(channel_url))
                return
            
            user = await get_user_with_stats(message.from_user.id)
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            
            if user:
                if message.from_user.username != user.get('username'):
                    await update_username(message.from_user.id, message.from_user.username or "")
                
                days = config.days_until_end()
                days_text = f"\nДо конца акции: {days} дн." if days > 0 else ""
                tickets_count = user.get('total_tickets') or user.get('valid_receipts') or 0
                
                welcome_msg = config_manager.get_message(
                    'welcome_back',
                    self.default_messages['welcome_back'],
                    bot_id=bot_id
                ).format(name=user['full_name'], count=tickets_count, days_text=days_text)
                
                await message.answer(welcome_msg, reply_markup=get_main_keyboard(config.is_admin(message.from_user.id), bot_type))
            else:
                # Delegate to registration if not registered
                from utils.states import Registration
                
                welcome_new_msg = config_manager.get_message(
                    'welcome_new',
                    self.default_messages['welcome_new'],
                    bot_id=bot_id
                )
                
                await message.answer(welcome_new_msg, reply_markup=get_cancel_keyboard())
                await state.set_state(Registration.name)

        @self.router.callback_query(F.data == "check_subscription")
        async def check_subscription_callback(callback: CallbackQuery, state: FSMContext, bot_id: int = None):
            if not bot_id:
                await callback.answer("Ошибка инициализации", show_alert=True)
                return
                
            is_sub, _, _ = await check_subscription(callback.from_user.id, callback.bot, bot_id)
            
            if is_sub:
                msg = config_manager.get_message('sub_check_success', self.default_messages['sub_check_success'], bot_id=bot_id)
                await callback.answer(msg)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                    
                # Continue login flow
                user = await get_user_with_stats(callback.from_user.id)
                bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
                
                if user:
                    tickets_count = user.get('total_tickets') or user.get('valid_receipts') or 0
                    welcome_msg = config_manager.get_message(
                        'welcome_back',
                        self.default_messages['welcome_back'],
                        bot_id=bot_id
                    ).format(name=user['full_name'], count=tickets_count, days_text="")
                    
                    await callback.message.answer(
                        welcome_msg,
                        reply_markup=get_main_keyboard(config.is_admin(callback.from_user.id), bot_type)
                    )
                else:
                    from utils.states import Registration
                    
                    welcome_new_msg = config_manager.get_message(
                        'welcome_new',
                        self.default_messages['welcome_new'],
                        bot_id=bot_id
                    )
                    
                    await callback.message.answer(welcome_new_msg, reply_markup=get_cancel_keyboard())
                    await state.set_state(Registration.name)
            else:
                fail_msg = config_manager.get_message('sub_check_fail', self.default_messages['sub_check_fail'], bot_id=bot_id)
                await callback.answer(fail_msg, show_alert=True)

        @self.router.message(F.text == "👤 Профиль")
        async def show_profile(message: Message, bot_id: int = None):
            if not bot_id: return
            user = await get_user_with_stats(message.from_user.id)
            if not user:
                await message.answer("Вы не зарегистрированы. Нажмите /start")
                return
            
            if message.from_user.username != user.get('username'):
                await update_username(message.from_user.id, message.from_user.username or "")
            
            # Get detailed ticket breakdown
            from database.bot_methods import get_user_tickets_breakdown
            breakdown = await get_user_tickets_breakdown(user['id'])
            
            wins = await get_user_wins(user['id'])
            wins_text = ""
            if wins:
                wins_text = f"\n\n🏆 Выигрыши: {len(wins)}"
                for w in wins[:3]:
                    wins_text += f"\n• {w['prize_name']}"
            
            days = config.days_until_end()
            days_text = f"\n\nДо конца акции: {days} дн." if days > 0 else ""
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')

            # Build enhanced profile message
            profile_text = f"👤 Ваш профиль\n\n"
            profile_text += f"Имя: {user['full_name']}\n"
            profile_text += f"Телефон: {user['phone']}\n\n"
            
            profile_text += f"═══════════════════\n"
            profile_text += f"🎫 ВАШИ БИЛЕТЫ: {breakdown['total']}\n"
            profile_text += f"═══════════════════\n"
            
            if bot_type == 'promo':
                if breakdown['from_promo'] > 0:
                    profile_text += f"  🔑 За промокоды: {breakdown['from_promo']}\n"
            else:
                if breakdown['from_receipts'] > 0:
                    profile_text += f"  🧾 За чеки: {breakdown['from_receipts']}\n"
            
            if breakdown['from_manual'] > 0:
                profile_text += f"  🎁 Бонусные: {breakdown['from_manual']}\n"
            
            if breakdown['total'] == 0:
                profile_text += f"  Пока нет билетов\n"
            
            profile_text += wins_text
            profile_text += days_text
            
            await message.answer(profile_text)

        @self.router.message(Command("help"))
        async def command_help(message: Message, bot_id: int = None):
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            help_key = f'help_{bot_type}'
            default_help = self.default_messages.get(help_key, self.default_messages['help_receipt'])
            
            help_msg = config_manager.get_message(help_key, default_help, bot_id=bot_id)
            await message.answer(help_msg, reply_markup=get_main_keyboard(config.is_admin(message.from_user.id), bot_type))

        @self.router.message(Command("status"))
        @self.router.message(Command("stats"))
        async def command_status(message: Message, bot_id: int = None):
            if not bot_id: return
            user = await get_user_with_stats(message.from_user.id)
            if not user:
                await message.answer(config_manager.get_message('not_registered', self.default_messages['not_registered'], bot_id=bot_id))
                return
            tickets_count = user.get('total_tickets') or user.get('valid_receipts') or 0
            status_msg = config_manager.get_message(
                'status', self.default_messages['status'], bot_id=bot_id
            ).format(name=user['full_name'], tickets=tickets_count, days=config.days_until_end())
            await message.answer(status_msg)

        @self.router.message(F.text == "🎫 Мои билеты")
        async def show_my_tickets(message: Message, bot_id: int = None):
            if not bot_id: return
            user = await get_user_with_stats(message.from_user.id)
            if not user:
                await message.answer(config_manager.get_message('error_auth', self.default_messages['error_auth'], bot_id=bot_id))
                return
            
            from database.bot_methods import get_user_tickets_breakdown, get_user_manual_tickets
            breakdown = await get_user_tickets_breakdown(user['id'])
            manual_list = await get_user_manual_tickets(user['id'])
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            
            # Content construction
            content = ""
            
            if breakdown['total'] == 0:
                empty_key = f'tickets_empty_{bot_type}'
                content = config_manager.get_message(empty_key, self.default_messages.get(empty_key, ""), bot_id=bot_id)
            else:
                content += f"🎟 Всего билетов: {breakdown['total']}\n\n"
                
                content += "📊 Откуда:\n"
                if bot_type == 'promo' and breakdown['from_promo'] > 0:
                    content += f"  🔑 Промокоды: {breakdown['from_promo']}\n"
                elif bot_type == 'receipt' and breakdown['from_receipts'] > 0:
                    content += f"  🧾 Чеки: {breakdown['from_receipts']}\n"
                
                if breakdown['from_manual'] > 0:
                    content += f"  🎁 Бонусы: {breakdown['from_manual']}\n"
                
                if manual_list:
                    content += "\n📋 Бонусные начисления:\n"
                    for t in manual_list[:3]:
                        reason = t.get('reason') or 'Бонус'
                        content += f"  • +{t['tickets']} — {reason}\n"
            
            # Mechanics footer
            mech_key = f'tickets_mechanics_{bot_type}'
            content += config_manager.get_message(mech_key, self.default_messages.get(mech_key, ""), bot_id=bot_id)
            
            # Main Frame
            full_msg = config_manager.get_message('tickets_info', self.default_messages['tickets_info'], bot_id=bot_id).format(content=content)
            
            await message.answer(full_msg)

        @self.router.message(F.text == "📋 Мои чеки")
        @self.router.message(F.text == "📋 Мои активации")
        async def show_receipts(message: Message, bot_id: int = None):
            if not bot_id: return
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            user = await get_user_with_stats(message.from_user.id)
            if not user or user['total_receipts'] == 0:
                key = f'no_receipts_{bot_type}'
                msg = config_manager.get_message(
                    key, 
                    self.default_messages.get(key, self.default_messages['no_receipts_receipt']),
                    bot_id=bot_id
                )
                await message.answer(msg)
                return
            
            receipts = await get_user_receipts(user['id'], limit=self.RECEIPTS_PER_PAGE, offset=0)
            total_pages = math.ceil(user['total_receipts'] / self.RECEIPTS_PER_PAGE)
            text = self._format_receipts(receipts, 1, user['total_receipts'], bot_id)
            kb = get_receipts_pagination_keyboard(1, total_pages) if total_pages > 1 else None
            await message.answer(text, reply_markup=kb)

        @self.router.callback_query(F.data.startswith("receipts_page_"))
        async def receipts_pagination(callback: CallbackQuery, bot_id: int = None):
            if not bot_id: return
            page = int(callback.data.split("_")[-1])
            user = await get_user_with_stats(callback.from_user.id)
            if not user: return
            offset = (page - 1) * self.RECEIPTS_PER_PAGE
            receipts = await get_user_receipts(user['id'], limit=self.RECEIPTS_PER_PAGE, offset=offset)
            total_pages = math.ceil(user['total_receipts'] / self.RECEIPTS_PER_PAGE)
            await callback.message.edit_text(
                self._format_receipts(receipts, page, user['total_receipts'], bot_id),
                reply_markup=get_receipts_pagination_keyboard(page, total_pages)
            )
            await callback.answer()

        @self.router.message(F.text == "ℹ️ Помощь")
        async def show_faq(message: Message, bot_id: int = None):
            faq_title = config_manager.get_message('faq_title', self.default_messages['faq_title'], bot_id=bot_id)
            await message.answer(faq_title, reply_markup=get_faq_keyboard(bot_manager.bot_types.get(bot_id, 'receipt')))

        @self.router.callback_query(F.data.startswith("faq_"))
        async def faq_callback(callback: CallbackQuery, bot_id: int = None):
            if not bot_id: return
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            action = callback.data
            
            if action == "faq_back":
                faq_title = config_manager.get_message('faq_title', self.default_messages['faq_title'], bot_id=bot_id)
                await callback.message.edit_text(faq_title, reply_markup=get_faq_keyboard(bot_type))
                await callback.answer()
                return

            # FAQ keys mapping to default message keys
            # faq_how -> faq_how_promo or faq_how_receipt
            msg_key = action
            if action in ['faq_how', 'faq_limit', 'faq_reject']:
                msg_key = f"{action}_{bot_type}"
            elif action in ['faq_win', 'faq_dates', 'faq_prizes', 'faq_raffle']:
                msg_key = action
            
            default_text = self.default_messages.get(msg_key, "Информация скоро появится")
            
            text = config_manager.get_message(msg_key, default_text, bot_id=bot_id).format(
                start=config.PROMO_START_DATE, end=config.PROMO_END_DATE, prizes=config.PROMO_PRIZES
            )
            await callback.message.edit_text(text, reply_markup=get_faq_back_keyboard())
            await callback.answer()

        @self.router.message(F.text == "🆘 Поддержка")
        async def show_support(message: Message, bot_id: int = None):
            text = config_manager.get_message('support_msg', self.default_messages['support_msg'], bot_id=bot_id)
            await message.answer(text, reply_markup=get_support_keyboard())

    def _format_receipts(self, receipts: list, page: int, total: int, bot_id: int = None) -> str:
        bot_type = bot_manager.bot_types.get(bot_id, 'receipt') if bot_id else 'receipt'
        
        list_key = f'receipts_list_{bot_type}'
        default_header = self.default_messages.get(list_key, self.default_messages['receipts_list_receipt'])
        
        header = config_manager.get_message(list_key, default_header, bot_id=bot_id).format(total=total)
        lines = [header]
        for r in receipts:
            status = "✅" if r['status'] == 'valid' else "❌"
            date = str(r['created_at'])[:10] if r.get('created_at') else ""
            sum_text = f" • {r['total_sum'] // 100}₽" if r.get('total_sum') else ""
            tickets = r.get('tickets', 1)
            tickets_text = f" • 🎫{tickets}" if tickets > 1 else ""
            product = f"\\n   └ {r['product_name'][:30]}" if r.get('product_name') else ""
            lines.append(f"\\n{status} {date}{sum_text}{tickets_text}{product}")
        return "".join(lines)

# Module instance
core_module = CoreModule()
