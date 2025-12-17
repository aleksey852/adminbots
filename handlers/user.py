"""
User handlers: start, profile, receipts list, FAQ, support
Combined from common.py + info.py
"""
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
import math

from database import get_user, get_user_with_stats, get_user_receipts, update_username, get_user_wins
from utils.states import Registration
from utils.config_manager import config_manager
from bot_manager import bot_manager
from keyboards import (
    get_main_keyboard, get_cancel_keyboard, get_receipts_pagination_keyboard,
    get_faq_keyboard, get_faq_back_keyboard, get_support_keyboard
)
import config

router = Router()
RECEIPTS_PER_PAGE = 10


# === Core Navigation ===

@router.message(Command("cancel"))
@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext, bot_id: int = None):
    await state.clear()
    
    count = 0
    if bot_id:
        user = await get_user_with_stats(message.from_user.id, bot_id)
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


@router.message(F.text == "🏠 В меню")
async def go_to_menu(message: Message, state: FSMContext, bot_id: int = None):
    await cancel_handler(message, state, bot_id)


@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext, bot_id: int = None):
    if not bot_id:
        await message.answer("Ошибка инициализации")
        return
        
    user = await get_user_with_stats(message.from_user.id, bot_id)
    
    if user:
        if message.from_user.username != user.get('username'):
            await update_username(message.from_user.id, message.from_user.username or "", bot_id)
        
        days = config.days_until_end()
        days_text = f"\nДо конца акции: {days} дн." if days > 0 else ""
        
        # Show tickets count instead of receipts
        tickets_count = user.get('total_tickets', user['valid_receipts'])
        
        # Use dynamic message from config_manager
        welcome_msg = config_manager.get_message(
            'welcome_back',
            "С возвращением, {name}! 👋\n\nВаших билетов: {count}{days_text}\n\nВыберите действие 👇",
            bot_id=bot_id
        ).format(name=user['full_name'], count=tickets_count, days_text=days_text)
        
        await message.answer(welcome_msg, reply_markup=get_main_keyboard(config.is_admin(message.from_user.id), bot_manager.bot_types.get(bot_id, 'receipt')))
    else:
        promo_name = config_manager.get_setting('PROMO_NAME', config.PROMO_NAME, bot_id=bot_id)
        prizes = config_manager.get_setting('PROMO_PRIZES', config.PROMO_PRIZES, bot_id=bot_id)
        
        welcome_new_msg = config_manager.get_message(
            'welcome_new',
            "🎉 Добро пожаловать в {promo_name}!\n\nПризы: {prizes}\n\nДля участия введите ваше имя:",
            bot_id=bot_id
        ).format(promo_name=promo_name, prizes=prizes)
        
        await message.answer(welcome_new_msg, reply_markup=get_cancel_keyboard())
        await state.set_state(Registration.name)


# === Profile & Receipts ===

@router.message(F.text == "👤 Мой профиль")
async def show_profile(message: Message, bot_id: int = None):
    if not bot_id: return
    bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
    user = await get_user_with_stats(message.from_user.id, bot_id)
    if not user:
        await message.answer("Вы не зарегистрированы. Нажмите /start")
        return
    
    if message.from_user.username != user.get('username'):
        await update_username(message.from_user.id, message.from_user.username or "", bot_id)
    
    wins = await get_user_wins(user['id'])
    wins_text = f"\n\n🏆 Выигрыши: {len(wins)}" if wins else ""
    for w in wins[:3]:
        wins_text += f"\n• {w['prize_name']}"
    
    days = config.days_until_end()
    days_text = f"\n\nДо конца акции: {days} дн." if days > 0 else ""
    
    tickets_count = user.get('total_tickets', user['valid_receipts'])

    default_profile = (
        "👤 Ваш профиль\n\nИмя: {name}\nТелефон: {phone}\n\n📊 Активаций: {total}\n🎫 Билетов: {tickets}{wins_text}{days_text}"
        if bot_type == 'promo'
        else "👤 Ваш профиль\n\nИмя: {name}\nТелефон: {phone}\n\n📊 Чеков загружено: {total}\n🎫 Билетов: {tickets}{wins_text}{days_text}"
    )
    profile_msg = config_manager.get_message('profile', default_profile, bot_id=bot_id).format(
        name=user['full_name'],
        phone=user['phone'],
        total=user['valid_receipts'],
        tickets=tickets_count,
        wins_text=wins_text,
        days_text=days_text,
    )
    
    await message.answer(profile_msg)


@router.message(Command("help"))
async def command_help(message: Message, bot_id: int = None):
    bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
    default_help = (
        "🤖 Что умеет бот:\n\n🔑 Ввести промокод — отправьте код сообщением\n👤 Мой профиль — ваша статистика\n📋 Мои активации — история промокодов\nℹ️ FAQ — частые вопросы\n🆘 Поддержка — связь с нами\n\nКоманды: /start /help /status /cancel"
        if bot_type == 'promo'
        else "🤖 Что умеет бот:\n\n🧾 Загрузить чек — отправьте QR-код\n👤 Мой профиль — ваша статистика\n📋 Мои чеки — история загрузок\nℹ️ FAQ — частые вопросы\n🆘 Поддержка — связь с нами\n\nКоманды: /start /help /status /cancel"
    )
    help_msg = config_manager.get_message('help', default_help, bot_id=bot_id)
    await message.answer(
        help_msg,
        reply_markup=get_main_keyboard(config.is_admin(message.from_user.id), bot_manager.bot_types.get(bot_id, 'receipt'))
    )


@router.message(Command("status"))
@router.message(Command("stats"))
async def command_status(message: Message, bot_id: int = None):
    if not bot_id: return
    user = await get_user_with_stats(message.from_user.id, bot_id)
    if not user:
        not_registered_msg = config_manager.get_message('not_registered', "Сначала /start", bot_id=bot_id)
        await message.answer(not_registered_msg)
        return
    
    tickets_count = user.get('total_tickets', user['valid_receipts'])
    
    status_msg = config_manager.get_message(
        'status',
        "📊 {name}\n\nБилетов: {tickets}\nДо конца: {days} дн.",
        bot_id=bot_id
    ).format(
        name=user['full_name'],
        tickets=tickets_count,
        days=config.days_until_end()
    )
    await message.answer(status_msg)


@router.message(F.text == "📋 Мои чеки")
@router.message(F.text == "📋 Мои активации")
async def show_receipts(message: Message, bot_id: int = None):
    if not bot_id: return
    bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
    user = await get_user_with_stats(message.from_user.id, bot_id)
    if not user:
        await message.answer("Вы не зарегистрированы. /start")
        return
    
    total = user['total_receipts']
    if total == 0:
        default_no_receipts = (
            "📋 У вас пока нет активаций\n\nНажмите «🔑 Ввести промокод» или отправьте код сообщением"
            if bot_type == 'promo'
            else "📋 У вас пока нет чеков\n\nНажмите «🧾 Загрузить чек»"
        )
        no_receipts_msg = config_manager.get_message(
            'no_receipts',
            default_no_receipts,
            bot_id=bot_id
        )
        await message.answer(no_receipts_msg)
        return
    
    receipts = await get_user_receipts(user['id'], limit=RECEIPTS_PER_PAGE, offset=0)
    total_pages = math.ceil(total / RECEIPTS_PER_PAGE)
    
    text = _format_receipts(receipts, 1, total, bot_id)
    kb = get_receipts_pagination_keyboard(1, total_pages) if total_pages > 1 else None
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("receipts_page_"))
async def receipts_pagination(callback: CallbackQuery, bot_id: int = None):
    if not bot_id: return
    page = int(callback.data.split("_")[-1])
    user = await get_user_with_stats(callback.from_user.id, bot_id)
    if not user:
        await callback.answer("Ошибка")
        return
    
    offset = (page - 1) * RECEIPTS_PER_PAGE
    receipts = await get_user_receipts(user['id'], limit=RECEIPTS_PER_PAGE, offset=offset)
    total_pages = math.ceil(user['total_receipts'] / RECEIPTS_PER_PAGE)
    
    await callback.message.edit_text(
        _format_receipts(receipts, page, user['total_receipts'], bot_id),
        reply_markup=get_receipts_pagination_keyboard(page, total_pages)
    )
    await callback.answer()


@router.callback_query(F.data == "receipts_current")
async def receipts_current_page(callback: CallbackQuery):
    await callback.answer()


def _format_receipts(receipts: list, page: int, total: int, bot_id: int = None) -> str:
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


# === FAQ ===

@router.message(F.text == "ℹ️ FAQ")
async def show_faq(message: Message, bot_id: int = None):
    faq_title = config_manager.get_message('faq_title', "❓ Частые вопросы\n\nВыберите тему:", bot_id=bot_id)
    await message.answer(faq_title, reply_markup=get_faq_keyboard(bot_manager.bot_types.get(bot_id, 'receipt')))


@router.callback_query(F.data == "faq_how")
async def faq_how(callback: CallbackQuery, bot_id: int = None):
    bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
    default_text = (
        "🎯 Как участвовать?\n\n1. Получите промокод\n2. Отправьте промокод сообщением в этот бот\n3. Получите билеты и ждите розыгрыша!\n\n💡 Чем больше билетов — тем выше шансы"
        if bot_type == 'promo'
        else "🎯 Как участвовать?\n\n1. Купите чипсы +VIBE\n2. Сохраните чек\n3. Сфотографируйте QR-код\n4. Отправьте фото в бот\n5. Ждите розыгрыша!\n\n💡 Каждая пачка = 1 билет!\nБольше пачек — выше шансы на выигрыш!"
    )
    text = config_manager.get_message(
        'faq_how',
        default_text,
        bot_id=bot_id
    )
    await callback.message.edit_text(text, reply_markup=get_faq_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "faq_limit")
async def faq_limit(callback: CallbackQuery, bot_id: int = None):
    bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
    default_text = (
        "🔢 Сколько промокодов можно активировать?\n\nОграничений нет!\n\nВажно:\n• Каждый промокод — один раз\n• Вводите код без лишних пробелов\n• Если код не принимается — проверьте символы"
        if bot_type == 'promo'
        else "🧾 Сколько чеков можно загрузить?\n\nОграничений нет!\n\nВажно:\n• Каждый чек — один раз\n• Нужны акционные товары\n• Чек не старше 30 дней"
    )
    text = config_manager.get_message(
        'faq_limit',
        default_text,
        bot_id=bot_id
    )
    await callback.message.edit_text(text, reply_markup=get_faq_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "faq_win")
async def faq_win(callback: CallbackQuery, bot_id: int = None):
    text = config_manager.get_message(
        'faq_win',
        "🏆 Как узнать о выигрыше?\n\nМы пришлём сообщение в этот бот!\n\nУбедитесь, что уведомления включены",
        bot_id=bot_id
    )
    await callback.message.edit_text(text, reply_markup=get_faq_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "faq_reject")
async def faq_reject(callback: CallbackQuery, bot_id: int = None):
    bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
    default_text = (
        "❌ Почему промокод не принят?\n\n• Код введён с ошибкой\n• Код уже использован\n• Код не относится к акции\n• Акция завершена\n\n💡 Если уверены, что код верный — напишите в поддержку"
        if bot_type == 'promo'
        else "❌ Почему чек не принят?\n\n• QR-код нечёткий\n• Нет акционных товаров\n• Чек старше 30 дней\n• Уже загружен\n\n💡 Свежий чек? Подождите 5-10 минут"
    )
    text = config_manager.get_message(
        'faq_reject',
        default_text,
        bot_id=bot_id
    )
    await callback.message.edit_text(text, reply_markup=get_faq_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "faq_dates")
async def faq_dates(callback: CallbackQuery, bot_id: int = None):
    days = config.days_until_end()
    status = f"Осталось: {days} дн." if days > 0 else "Акция завершена"
    text = config_manager.get_message(
        'faq_dates',
        "📅 Сроки акции\n\nНачало: {start}\nОкончание: {end}\n\n{status}",
        bot_id=bot_id
    ).format(start=config.PROMO_START_DATE, end=config.PROMO_END_DATE, status=status)
    
    await callback.message.edit_text(text, reply_markup=get_faq_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "faq_prizes")
async def faq_prizes(callback: CallbackQuery, bot_id: int = None):
    bot_type = bot_manager.bot_types.get(bot_id, 'receipt')
    default_text = (
        "🎁 Призы\n\n{prizes}\n\nБольше билетов = выше шансы!"
        if bot_type == 'promo'
        else "🎁 Призы\n\n{prizes}\n\nБольше чеков = выше шансы!"
    )
    text = config_manager.get_message(
        'faq_prizes',
        default_text,
        bot_id=bot_id
    ).format(prizes=config.PROMO_PRIZES)
    
    await callback.message.edit_text(text, reply_markup=get_faq_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "faq_back")
async def faq_back(callback: CallbackQuery, bot_id: int = None):
    faq_title = config_manager.get_message('faq_title', "❓ Частые вопросы\n\nВыберите тему:", bot_id=bot_id)
    await callback.message.edit_text(
        faq_title,
        reply_markup=get_faq_keyboard(bot_manager.bot_types.get(bot_id, 'receipt'))
    )
    await callback.answer()


# === Support ===

@router.message(F.text == "🆘 Поддержка")
async def show_support(message: Message, bot_id: int = None):
    text = config_manager.get_message('support_msg', "🆘 Нужна помощь?\n\nНапишите нам!", bot_id=bot_id)
    await message.answer(text, reply_markup=get_support_keyboard())
