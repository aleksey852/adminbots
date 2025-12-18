"""Settings router: promo settings, support, messages"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Dict
import logging

import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])

# Editable promo settings
PROMO_FIELDS = [
    ("PROMO_START_DATE", "Дата начала (YYYY-MM-DD)"),
    ("PROMO_END_DATE", "Дата окончания (YYYY-MM-DD)"),
]

SUPPORT_FIELDS = [
    ("SUPPORT_EMAIL", "Email поддержки"),
    ("SUPPORT_TELEGRAM", "Telegram поддержки (@username)"),
]

SUBSCRIPTION_FIELDS = [
    ("SUBSCRIPTION_REQUIRED", "Требовать подписку на канал (true/false)"),
    ("SUBSCRIPTION_CHANNEL_ID", "ID канала (напр. -1001234567890)"),
    ("SUBSCRIPTION_CHANNEL_URL", "Ссылка на канал"),
]

# Will be set by setup_routes
templates = None
get_current_user = None
verify_csrf_token = None
get_template_context = None


def setup_routes(
    app_templates: Jinja2Templates,
    auth_get_current_user,
    auth_verify_csrf_token,
    context_helper
):
    """Setup routes with dependencies"""
    global templates, get_current_user, verify_csrf_token, get_template_context
    templates = app_templates
    get_current_user = auth_get_current_user
    verify_csrf_token = auth_verify_csrf_token
    get_template_context = context_helper

    @router.get("", response_class=HTMLResponse)
    async def settings_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
        from utils.config_manager import config_manager
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        if not config_manager._initialized:
            await config_manager.load()
        
        bot_id = bot['id']
        
        promo_fields = []
        for key, label in PROMO_FIELDS:
            val = config_manager.get_setting(key, getattr(config, key, ""), bot_id)
            promo_fields.append((key, label, val))
            
        # Add keyword settings only for receipt bots
        if bot.get('type') == 'receipt':
            keyword_fields = [
                ("TARGET_KEYWORDS", "Ключевые слова товаров (через запятую)"),
                ("EXCLUDED_KEYWORDS", "Слова-исключения товаров (через запятую)")
            ]
            for key, label in keyword_fields:
                val = config_manager.get_setting(key, getattr(config, key, ""), bot_id)
                promo_fields.append((key, label, val))
        
        db_settings = await config_manager.get_all_settings(bot_id)
        
        return templates.TemplateResponse("settings/index.html", get_template_context(
            request, user=user, title="Настройки",
            promo_fields=promo_fields, db_settings=db_settings,
            updated=updated
        ))

    @router.post("/update", dependencies=[Depends(verify_csrf_token)])
    async def update_setting(
        request: Request,
        key: str = Form(...),
        value: str = Form(...),
        user: str = Depends(get_current_user)
    ):
        from utils.config_manager import config_manager
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        await config_manager.set_setting(key, value, bot['id'])
        return RedirectResponse(url="/settings?updated=1", status_code=303)

    # === Support Settings ===
    
    @router.get("/support", response_class=HTMLResponse)
    async def support_settings_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
        from utils.config_manager import config_manager
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")
        
        if not config_manager._initialized:
            await config_manager.load()

        support_fields = []
        for key, label in SUPPORT_FIELDS:
            val = config_manager.get_setting(key, getattr(config, key, ""), bot['id'])
            support_fields.append((key, label, val))
        
        return templates.TemplateResponse("settings/support.html", get_template_context(
            request, user=user, title="Настройки поддержки",
            support_fields=support_fields, updated=updated
        ))

    @router.post("/support/update", dependencies=[Depends(verify_csrf_token)])
    async def update_support_setting(
        request: Request,
        key: str = Form(...),
        value: str = Form(...),
        user: str = Depends(get_current_user)
    ):
        from utils.config_manager import config_manager
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        await config_manager.set_setting(key, value, bot['id'])
        return RedirectResponse(url="/settings/support?updated=1", status_code=303)

    # === Subscription Settings ===
    
    @router.get("/subscription", response_class=HTMLResponse)
    async def subscription_settings_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
        from utils.config_manager import config_manager
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")
        
        if not config_manager._initialized:
            await config_manager.load()

        subscription_fields = []
        defaults = {"SUBSCRIPTION_REQUIRED": "false", "SUBSCRIPTION_CHANNEL_ID": "", "SUBSCRIPTION_CHANNEL_URL": ""}
        for key, label in SUBSCRIPTION_FIELDS:
            val = config_manager.get_setting(key, defaults.get(key, ""), bot['id'])
            subscription_fields.append((key, label, val))
        
        return templates.TemplateResponse("settings/subscription.html", get_template_context(
            request, user=user, title="Проверка подписки",
            subscription_fields=subscription_fields, updated=updated
        ))

    @router.post("/subscription/update", dependencies=[Depends(verify_csrf_token)])
    async def update_subscription_setting(
        request: Request,
        key: str = Form(...),
        value: str = Form(...),
        user: str = Depends(get_current_user)
    ):
        from utils.config_manager import config_manager
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        await config_manager.set_setting(key, value, bot['id'])
        return RedirectResponse(url="/settings/subscription?updated=1", status_code=303)

    # === Messages ===
    
    @router.get("/messages", response_class=HTMLResponse)
    async def messages_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
        from utils.config_manager import config_manager
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        if not config_manager._initialized:
            await config_manager.load()
        
        messages = await config_manager.get_all_messages(bot['id'])
        
        common_messages = [
            ("welcome_new", "Приветствие нового пользователя (при /start)", 
             "🎉 Добро пожаловать в {promo_name}!\n\nПризы: {prizes}"),
            ("welcome_back", "Приветствие при возврате (повторный /start)", 
             "С возвращением, {name}! 👋\n\nВаших билетов: {count}"),
            ("reg_phone_prompt", "Запрос телефона при регистрации",
             "Отлично, {name}! 👋\n\nОтправьте номер телефона:"),
            ("reg_success", "Успешная регистрация",
             "✅ Регистрация завершена!"),
            ("reg_cancel", "Отмена регистрации",
             "Хорошо! Возвращайтесь 👋"),
            ("support_msg", "Сообщение при нажатии 🆘 Поддержка",
             "🆘 Нужна помощь?\n\nНапишите нам!"),
        ]

        receipt_messages = [
            ("upload_instruction", "Инструкция при загрузке чека",
             "📸 Отправьте фото QR-кода с чека\n\nВаших билетов: {count}"),
            ("receipt_valid", "Чек успешно принят",
             "✅ Чек принят!\n\nВсего билетов: {count} 🎯"),
            ("receipt_first", "Первый чек пользователя",
             "🎉 Поздравляем с первым чеком!\n\nВы в розыгрыше! Загружайте ещё 🎯"),
            ("receipt_duplicate", "Чек уже был загружен",
             "ℹ️ Этот чек уже загружен"),
            ("receipt_no_product", "Нет акционных товаров в чеке",
             "😔 В чеке нет акционных товаров"),
            ("scan_failed", "Не удалось распознать QR-код",
             "🔍 Не удалось распознать чек\n\n• Сфотографируйте ближе\n• Улучшите освещение"),
            ("profile", "Профиль пользователя (кнопка 👤)",
             "👤 Ваш профиль\n\nИмя: {name}\nТелефон: {phone}\n\n📊 Чеков: {total}\n🎫 Билетов: {tickets}"),
            ("no_receipts", "У пользователя нет чеков",
             "📋 У вас пока нет чеков\n\nНажмите «🧾 Загрузить чек»"),
            ("faq_how", "FAQ: Как участвовать",
             "🎯 Как участвовать?\n\n1. Купите акционные товары\n2. Сфотографируйте QR-код\n3. Загрузите в бот"),
            ("faq_win", "FAQ: Как узнать о выигрыше",
             "🏆 Как узнать о выигрыше?\n\nМы пришлём сообщение в этот бот!"),
        ]

        promo_messages = [
            ("promo_prompt", "Приглашение ввести промокод",
             "🔑 Введите промокод из 12 символов\n\n💡 Пример: ABCD12345678"),
            ("promo_activated", "Промокод успешно активирован",
             "✅ Промокод активирован!\n\n🎟 Получено билетов: {tickets}\n📊 Всего билетов: {total}"),
            ("promo_not_found", "Промокод не найден",
             "❌ Промокод не найден\n\nПроверьте правильность ввода"),
            ("promo_already_used", "Промокод уже использован",
             "⚠️ Этот промокод уже был использован"),
            ("promo_wrong_format", "Неверный формат промокода",
             "⚠️ Промокод должен содержать ровно 12 символов"),
            ("profile", "Профиль пользователя (кнопка 👤)",
             "👤 Ваш профиль\n\nИмя: {name}\nТелефон: {phone}\n\n🎫 Билетов: {tickets}"),
            ("faq_how", "FAQ: Как участвовать",
             "🎯 Как участвовать?\n\n1. Получите промокод\n2. Введите его в боте"),
            ("faq_win", "FAQ: Как узнать о выигрыше",
             "🏆 Как узнать о выигрыше?\n\nМы пришлём сообщение в этот бот!"),
        ]

        default_messages = common_messages
        if bot['type'] == 'receipt':
            default_messages += receipt_messages
        elif bot['type'] == 'promo':
            default_messages += promo_messages

        return templates.TemplateResponse("settings/messages.html", get_template_context(
            request, user=user, title="Тексты сообщений",
            messages=messages, default_messages=default_messages,
            updated=updated
        ))

    @router.post("/messages/update", dependencies=[Depends(verify_csrf_token)])
    async def update_message(
        request: Request,
        key: str = Form(...),
        text: str = Form(...),
        user: str = Depends(get_current_user)
    ):
        from utils.config_manager import config_manager
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        await config_manager.set_message(key, text, bot['id'])
        return RedirectResponse(url="/settings/messages?updated=1", status_code=303)

    return router
