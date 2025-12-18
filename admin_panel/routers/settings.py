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

RAFFLE_FIELDS = [
    ("ENABLE_MONTHLY_RAFFLE", "Включить ежемесячный розыгрыш (true/false)"),
    ("MONTHLY_RAFFLE_PRIZE", "Приз ежемесячного розыгрыша"),
    ("MONTHLY_RAFFLE_COUNT", "Количество победителей"),
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
        if not (bot := request.state.bot): return RedirectResponse("/")
        if not config_manager._initialized: await config_manager.load()
        
        bot_id = bot['id']
        promo_fields = [(k, l, config_manager.get_setting(k, getattr(config, k, ""), bot_id)) for k, l in PROMO_FIELDS]
        
        if bot.get('type') == 'receipt':
            for k, l in [("TARGET_KEYWORDS", "Ключевые слова товаров"), ("EXCLUDED_KEYWORDS", "Слова-исключения")]:
                promo_fields.append((k, l, config_manager.get_setting(k, getattr(config, k, ""), bot_id)))
        
        return templates.TemplateResponse("settings/index.html", get_template_context(
            request, user=user, title="Настройки",
            promo_fields=promo_fields, db_settings=await config_manager.get_all_settings(bot_id),
            updated=updated
        ))

    @router.post("/update", dependencies=[Depends(verify_csrf_token)])
    async def update_setting(request: Request, key: str = Form(...), value: str = Form(...), user: str = Depends(get_current_user)):
        from utils.config_manager import config_manager
        if not (bot := request.state.bot): return RedirectResponse("/")
        await config_manager.set_setting(key, value, bot['id'])
        return RedirectResponse("/settings?updated=1", 303)

    @router.get("/support", response_class=HTMLResponse)
    async def support_settings_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
        from utils.config_manager import config_manager
        if not (bot := request.state.bot): return RedirectResponse("/")
        if not config_manager._initialized: await config_manager.load()

        fields = [(k, l, config_manager.get_setting(k, getattr(config, k, ""), bot['id'])) for k, l in SUPPORT_FIELDS]
        return templates.TemplateResponse("settings/support.html", get_template_context(request, user=user, title="Поддержка", support_fields=fields, updated=updated))

    @router.post("/support/update", dependencies=[Depends(verify_csrf_token)])
    async def update_support_setting(request: Request, key: str = Form(...), value: str = Form(...), user: str = Depends(get_current_user)):
        from utils.config_manager import config_manager
        if not (bot := request.state.bot): return RedirectResponse("/")
        await config_manager.set_setting(key, value, bot['id'])
        return RedirectResponse("/settings/support?updated=1", 303)

    @router.get("/subscription", response_class=HTMLResponse)
    async def subscription_settings_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
        from utils.config_manager import config_manager
        if not (bot := request.state.bot): return RedirectResponse("/")
        if not config_manager._initialized: await config_manager.load()

        defaults = {"SUBSCRIPTION_REQUIRED": "false", "SUBSCRIPTION_CHANNEL_ID": "", "SUBSCRIPTION_CHANNEL_URL": ""}
        fields = [(k, l, config_manager.get_setting(k, defaults.get(k, ""), bot['id'])) for k, l in SUBSCRIPTION_FIELDS]
        return templates.TemplateResponse("settings/subscription.html", get_template_context(request, user=user, title="Подписка", subscription_fields=fields, updated=updated))

    @router.post("/subscription/update", dependencies=[Depends(verify_csrf_token)])
    async def update_subscription_setting(request: Request, key: str = Form(...), value: str = Form(...), user: str = Depends(get_current_user)):
        from utils.config_manager import config_manager
        if not (bot := request.state.bot): return RedirectResponse("/")
        await config_manager.set_setting(key, value, bot['id'])
        return RedirectResponse("/settings/subscription?updated=1", 303)

    @router.get("/raffle", response_class=HTMLResponse)
    async def raffle_settings_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
        from utils.config_manager import config_manager
        if not (bot := request.state.bot): return RedirectResponse("/")
        if not config_manager._initialized: await config_manager.load()

        defaults = {"ENABLE_MONTHLY_RAFFLE": "false", "MONTHLY_RAFFLE_PRIZE": "VIP статус", "MONTHLY_RAFFLE_COUNT": "1"}
        fields = [(k, l, config_manager.get_setting(k, defaults.get(k, ""), bot['id'])) for k, l in RAFFLE_FIELDS]
        return templates.TemplateResponse("settings/raffle.html", get_template_context(request, user=user, title="Настройки розыгрышей", raffle_fields=fields, updated=updated))

    @router.post("/raffle/update", dependencies=[Depends(verify_csrf_token)])
    async def update_raffle_setting(request: Request, key: str = Form(...), value: str = Form(...), user: str = Depends(get_current_user)):
        from utils.config_manager import config_manager
        if not (bot := request.state.bot): return RedirectResponse("/")
        await config_manager.set_setting(key, value, bot['id'])
        return RedirectResponse("/settings/raffle?updated=1", 303)

    @router.get("/messages", response_class=HTMLResponse)
    async def messages_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
        from utils.config_manager import config_manager
        if not (bot := request.state.bot): return RedirectResponse("/")
        if not config_manager._initialized: await config_manager.load()
        
        common = [
            ("welcome_new", "Приветствие нового пользователя", "🎉 Добро пожаловать!"),
            ("welcome_back", "Приветствие при возврате", "С возвращением!"),
            ("reg_phone_prompt", "Запрос телефона", "Отправьте номер телефона:"),
            ("reg_success", "Успешная регистрация", "✅ Регистрация завершена!"),
            ("support_msg", "Сообщение поддержки", "🆘 Нужна помощь?"),
        ]
        receipts = [
            ("upload_instruction", "Инструкция загрузки чека", "📸 Отправьте фото QR-кода"),
            ("receipt_valid", "Чек принят", "✅ Чек принят!"),
            ("scan_failed", "Ошибка сканирования", "🔍 Не удалось распознать"),
        ]
        promo = [
            ("promo_prompt", "Запрос промокода", "🔑 Введите промокод"),
            ("promo_activated", "Промокод активирован", "✅ Активировано!"),
        ]

        defaults = common + (receipts if bot['type'] == 'receipt' else promo)
        return templates.TemplateResponse("settings/messages.html", get_template_context(
            request, user=user, title="Тексты",
            messages=await config_manager.get_all_messages(bot['id']), 
            default_messages=defaults, updated=updated
        ))

    @router.post("/messages/update", dependencies=[Depends(verify_csrf_token)])
    async def update_message(request: Request, key: str = Form(...), text: str = Form(...), user: str = Depends(get_current_user)):
        from utils.config_manager import config_manager
        if not (bot := request.state.bot): return RedirectResponse("/")
        await config_manager.set_message(key, text, bot['id'])
        return RedirectResponse("/settings/messages?updated=1", 303)

    return router
