"""
Core Module - Base bot navigation and user profile
"""
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
import math
import logging

from modules.base import BotModule
from database.bot_methods import get_user_with_stats, get_user_receipts, update_username, get_user_wins
from utils.config_manager import config_manager
from bot_manager import bot_manager
from .keyboards import (
    get_main_keyboard, get_cancel_keyboard, get_receipts_pagination_keyboard,
    get_faq_keyboard, get_faq_back_keyboard, get_support_keyboard
)
import config

logger = logging.getLogger(__name__)

class CoreModule(BotModule):
    """Base bot functionality: start, menu, profile, FAQ, support"""
    
    name = "core"
    version = "1.0.0"
    description = "Базовый функционал: меню, профиль, FAQ"
    default_enabled = True
    
    RECEIPTS_PER_PAGE = 10
    
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
                    count = user.get('total_tickets', user['valid_receipts'])
            
            cancel_msg = config_manager.get_message(
                'cancel_msg',
                "Выберите действие 👇\nВаших билетов: {count}",
                bot_id=bot_id
            ).format(count=count)
            
            await message.answer(
                cancel_msg,
                reply_markup=get_main_keyboard(config.is_admin(message.from_user.id), bot_manager.bot_types.get(bot_id, 'receipt'))
            )

        @self.router.message(F.text == "🏠 В меню")
        async def go_to_menu(message: Message, state: FSMContext, bot_id: int = None):
            await cancel_handler(message, state, bot_id)

        @self.router.message(CommandStart())
        async def command_start(message: Message, state: FSMContext, bot_id: int = None):
            if not bot_id:
                await message.answer("Ошибка инициализации")
                return
            
            # Check subscription
            subscription_required = config_manager.get_setting('SUBSCRIPTION_REQUIRED', 'false', bot_id=bot_id)
            if subscription_required.lower() == 'true':
                channel_id = config_manager.get_setting('SUBSCRIPTION_CHANNEL_ID', '', bot_id=bot_id)
                channel_url = config_manager.get_setting('SUBSCRIPTION_CHANNEL_URL', '', bot_id=bot_id)
                
                if channel_id:
                    try:
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        bot = message.bot
                        member = await bot.get_chat_member(chat_id=int(channel_id), user_id=message.from_user.id)
                        
                        if member.status not in ['member', 'administrator', 'creator']:
                            buttons = []
                            if channel_url:
                                buttons.append([InlineKeyboardButton(text="📢 Подписаться", url=channel_url)])
                            buttons.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")])
                            
                            await message.answer(
                                "⚠️ Для участия в акции необходимо подписаться на наш канал!",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                            )
                            return
                    except Exception as e:
                        logger.warning(f"Subscription check failed: {e}")
            
            user = await get_user_with_stats(message.from_user.id)
            
            if user:
                if message.from_user.username != user.get('username'):
                    await update_username(message.from_user.id, message.from_user.username or "")
                
                days = config.days_until_end()
                days_text = f"\nДо конца акции: {days} дн." if days > 0 else ""
                tickets_count = user.get('total_tickets', user['valid_receipts'])
                
                welcome_msg = config_manager.get_message(
                    'welcome_back',
                    "С возвращением, {name}! 👋\n\nВаших билетов: {count}{days_text}\n\nВыберите действие 👇",
                    bot_id=bot_id
                ).format(name=user['full_name'], count=tickets_count, days_text=days_text)
                
                await message.answer(welcome_msg, reply_markup=get_main_keyboard(config.is_admin(message.from_user.id), bot_manager.bot_types.get(bot_id, 'receipt')))
            else:
                # Delegate to registration if not registered
                # We need to import registration state here or use a generic one
                from utils.states import Registration
                promo_name = config_manager.get_setting('PROMO_NAME', config.PROMO_NAME, bot_id=bot_id)
                prizes = config_manager.get_setting('PROMO_PRIZES', config.PROMO_PRIZES, bot_id=bot_id)
                
                welcome_new_msg = config_manager.get_message(
                    'welcome_new',
                    "🎉 Добро пожаловать в {promo_name}!\n\nПризы: {prizes}\n\nДля участия введите ваше имя:",
                    bot_id=bot_id
                ).format(promo_name=promo_name, prizes=prizes)
                
                await message.answer(welcome_new_msg, reply_markup=get_cancel_keyboard())
                await state.set_state(Registration.name)

        @self.router.callback_query(F.data == "check_subscription")
        async def check_subscription_callback(callback: CallbackQuery, state: FSMContext, bot_id: int = None):
            if not bot_id: return
            channel_id = config_manager.get_setting('SUBSCRIPTION_CHANNEL_ID', '', bot_id=bot_id)
            if channel_id:
                try:
                    member = await callback.bot.get_chat_member(chat_id=int(channel_id), user_id=callback.from_user.id)
                    if member.status in ['member', 'administrator', 'creator']:
                        await callback.answer("✅ Подписка подтверждена!")
                        await callback.message.delete()
                        await command_start(callback.message, state, bot_id)
                        return
                    else:
                        await callback.answer("❌ Вы ещё не подписаны на канал!", show_alert=True)
                        return
                except Exception as e:
                    await callback.answer(f"Ошибка: {str(e)[:50]}", show_alert=True)
                    return
            await callback.message.delete()
            await command_start(callback.message, state, bot_id)

        @self.router.message(F.text == "👤 Мой профиль")
        async def show_profile(message: Message, bot_id: int = None):
            if not bot_id: return
            user = await get_user_with_stats(message.from_user.id)
            if not user:
                await message.answer("Вы не зарегистрированы. Нажмите /start")
                return
            
            if message.from_user.username != user.get('username'):
                await update_username(message.from_user.id, message.from_user.username or "")
            
            wins = await get_user_wins(user['id'])
            wins_text = f"\n\n🏆 Выигрыши: {len(wins)}" if wins else ""
            for w in wins[:3]:
                wins_text += f"\n• {w['prize_name']}"
            
            days = config.days_until_end()
            days_text = f"\n\nДо конца акции: {days} дн." if days > 0 else ""
            tickets_count = user.get('total_tickets', user['valid_receipts'])
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')

            default_profile = (
                "👤 Ваш профиль\n\nИмя: {name}\nТелефон: {phone}\n\n📊 Активаций: {total}\n🎫 Билетов: {tickets}{wins_text}{days_text}"
                if bot_type == 'promo'
                else "👤 Ваш профиль\n\nИмя: {name}\nТелефон: {phone}\n\n📊 Чеков загружено: {total}\n🎫 Билетов: {tickets}{wins_text}{days_text}"
            )
            profile_msg = config_manager.get_message('profile', default_profile, bot_id=bot_id).format(
                name=user['full_name'], phone=user['phone'], total=user['valid_receipts'],
                tickets=tickets_count, wins_text=wins_text, days_text=days_text,
            )
            await message.answer(profile_msg)

        @self.router.message(Command("help"))
        async def command_help(message: Message, bot_id: int = None):
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            default_help = (
                "🤖 Что умеет бот:\n\n🔑 Ввести промокод — отправьте код сообщением\n👤 Мой профиль — ваша статистика\n📋 Мои активации — история промокодов\nℹ️ FAQ — частые вопросы\n🆘 Поддержка — связь с нами\n\nКоманды: /start /help /status /cancel"
                if bot_type == 'promo'
                else "🤖 Что умеет бот:\n\n🧾 Загрузить чек — отправьте QR-код\n👤 Мой профиль — ваша статистика\n📋 Мои чеки — история загрузок\nℹ️ FAQ — частые вопросы\n🆘 Поддержка — связь с нами\n\nКоманды: /start /help /status /cancel"
            )
            help_msg = config_manager.get_message('help', default_help, bot_id=bot_id)
            await message.answer(help_msg, reply_markup=get_main_keyboard(config.is_admin(message.from_user.id), bot_type))

        @self.router.message(Command("status"))
        @self.router.message(Command("stats"))
        async def command_status(message: Message, bot_id: int = None):
            if not bot_id: return
            user = await get_user_with_stats(message.from_user.id)
            if not user:
                await message.answer(config_manager.get_message('not_registered', "Сначала /start", bot_id=bot_id))
                return
            tickets_count = user.get('total_tickets', user['valid_receipts'])
            status_msg = config_manager.get_message(
                'status', "📊 {name}\n\nБилетов: {tickets}\nДо конца: {days} дн.", bot_id=bot_id
            ).format(name=user['full_name'], tickets=tickets_count, days=config.days_until_end())
            await message.answer(status_msg)

        @self.router.message(F.text == "📋 Мои чеки")
        @self.router.message(F.text == "📋 Мои активации")
        async def show_receipts(message: Message, bot_id: int = None):
            if not bot_id: return
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            user = await get_user_with_stats(message.from_user.id)
            if not user or user['total_receipts'] == 0:
                msg = config_manager.get_message(
                    'no_receipts', 
                    "📋 У вас пока нет активаций" if bot_type == 'promo' else "📋 У вас пока нет чеков",
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

        @self.router.message(F.text == "ℹ️ FAQ")
        async def show_faq(message: Message, bot_id: int = None):
            faq_title = config_manager.get_message('faq_title', "❓ Частые вопросы\n\nВыберите тему:", bot_id=bot_id)
            await message.answer(faq_title, reply_markup=get_faq_keyboard(bot_manager.bot_types.get(bot_id, 'receipt')))

        @self.router.callback_query(F.data.startswith("faq_"))
        async def faq_callback(callback: CallbackQuery, bot_id: int = None):
            if not bot_id: return
            bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
            action = callback.data
            
            if action == "faq_back":
                faq_title = config_manager.get_message('faq_title', "❓ Частые вопросы\n\nВыберите тему:", bot_id=bot_id)
                await callback.message.edit_text(faq_title, reply_markup=get_faq_keyboard(bot_type))
                await callback.answer()
                return

            # Simplified mapping for FAQ responses
            faq_map = {
                "faq_how": {
                    "promo": "🎯 Как участвовать?\n\n1. Получите промокод\n2. Отправьте промокод сообщением в этот бот\n3. Получите билеты и ждите розыгрыша!",
                    "receipt": "🎯 Как участвовать?\n\n1. Купите чипсы +VIBE\n2. Сохраните чек\n3. Сфотографируйте QR-код\n4. Отправьте фото в бот"
                },
                "faq_limit": {
                    "promo": "🔢 Сколько промокодов можно активировать?\n\nОграничений нет!",
                    "receipt": "🧾 Сколько чеков можно загрузить?\n\nОграничений нет!"
                },
                "faq_win": "🏆 Как узнать о выигрыше?\n\nМы пришлём сообщение в этот бот!",
                "faq_reject": {
                    "promo": "❌ Почему промокод не принят?\n\n• Код введён с ошибкой\n• Код уже использован",
                    "receipt": "❌ Почему чек не принят?\n\n• QR-код нечёткий\n• Нет акционных товаров"
                },
                "faq_dates": "📅 Сроки акции\n\nНачало: {start}\nОкончание: {end}",
                "faq_prizes": "🎁 Призы\n\n{prizes}"
            }
            
            content = faq_map.get(action, "Информация скоро появится")
            if isinstance(content, dict):
                content = content.get(bot_type, content.get("receipt"))
            
            text = config_manager.get_message(action, content, bot_id=bot_id).format(
                start=config.PROMO_START_DATE, end=config.PROMO_END_DATE, prizes=config.PROMO_PRIZES
            )
            await callback.message.edit_text(text, reply_markup=get_faq_back_keyboard())
            await callback.answer()

        @self.router.message(F.text == "🆘 Поддержка")
        async def show_support(message: Message, bot_id: int = None):
            text = config_manager.get_message('support_msg', "🆘 Нужна помощь?\n\nНапишите нам!", bot_id=bot_id)
            await message.answer(text, reply_markup=get_support_keyboard())

    def _format_receipts(self, receipts: list, page: int, total: int, bot_id: int = None) -> str:
        bot_type = bot_manager.bot_types.get(bot_id, 'receipt') if bot_id else 'receipt'
        default_header = "📋 Ваши активации ({total})\n" if bot_type == 'promo' else "📋 Ваши чеки ({total})\n"
        header = config_manager.get_message('receipts_list', default_header, bot_id=bot_id).format(total=total)
        lines = [header]
        for r in receipts:
            status = "✅" if r['status'] == 'valid' else "❌"
            date = str(r['created_at'])[:10] if r.get('created_at') else ""
            sum_text = f" • {r['total_sum'] // 100}₽" if r.get('total_sum') else ""
            tickets = r.get('tickets', 1)
            tickets_text = f" • 🎫{tickets}" if tickets > 1 else ""
            product = f"\n   └ {r['product_name'][:30]}" if r.get('product_name') else ""
            lines.append(f"\n{status} {date}{sum_text}{tickets_text}{product}")
        return "".join(lines)

# Module instance
core_module = CoreModule()
