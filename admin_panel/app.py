"""Admin Panel - FastAPI app with full management capabilities"""
from fastapi import FastAPI, Request, Depends, HTTPException, status, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from jose import jwt, JWTError
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Dict, List
import sys
import os
import json
import uuid
import time
import secrets
import aiofiles
import asyncio
import logging
import subprocess

# Ensure project root is in path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config
from database import (
    get_stats, get_participants_count, get_stats_by_days, get_recent_campaigns,
    get_active_bots, get_bot, get_users_paginated, get_total_users_count, search_users,
    get_user_detail, get_user_receipts_detailed, add_campaign, add_receipt, block_user,
    get_all_receipts_paginated, get_total_receipts_count, get_recent_raffles_with_winners,
    get_total_tickets_count
)

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths relative to this file
ADMIN_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = ADMIN_DIR / "templates"
STATIC_DIR = ADMIN_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
UPLOADS_DIR = ADMIN_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Buster Admin")

# Lifespan for DB initialization
from contextlib import asynccontextmanager
from database import init_db, close_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await init_db()
        logger.info("Database pool initialized in Admin Panel")
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}")
    
    yield
    
    # Shutdown
    await close_db()

app = FastAPI(title="Admin Bots Panel", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24
DB_OPERATION_TIMEOUT = 10.0
SLOW_REQUEST_THRESHOLD = 3.0


@app.middleware("http")
async def context_middleware(request: Request, call_next):
    """Middleware to set active bot context"""
    start_time = time.time()
    
    # 1. Load active bots
    try:
        bots = await get_active_bots()
        request.state.bots = bots
    except Exception as e:
        logger.error(f"Failed to load bots: {e}")
        request.state.bots = []
    
    # 2. Determine active bot
    active_bot_id = request.session.get("active_bot_id")
    active_bot = None
    
    if active_bot_id:
        active_bot = await get_bot(active_bot_id)
        if not active_bot:
            active_bot_id = None # Invalid or deleted
            
    if not active_bot and request.state.bots:
        active_bot = request.state.bots[0]
        request.session["active_bot_id"] = active_bot['id']
    
    request.state.bot = active_bot
    
    # Log request
    logger.info(f"➡️  {request.method} {request.url.path} (Bot: {active_bot['name'] if active_bot else 'None'})")
    
    try:
        response = await call_next(request)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"❌ Request failed: {request.method} {request.url.path} - {duration:.2f}s - {e}")
        raise
    
    duration = time.time() - start_time
    if duration > SLOW_REQUEST_THRESHOLD:
        logger.warning(f"🐢 Slow request: {duration:.2f}s")
    
    return response

app.add_middleware(SessionMiddleware, secret_key=config.ADMIN_SECRET_KEY)


# Editable promo settings
PROMO_FIELDS = [
    ("PROMO_NAME", "Название акции"),
    ("PROMO_START_DATE", "Дата начала (YYYY-MM-DD)"),
    ("PROMO_END_DATE", "Дата окончания (YYYY-MM-DD)"),
    ("PROMO_PRIZES", "Призы (через запятую)"),
    ("TARGET_KEYWORDS", "Ключевые слова товаров (через запятую)"),
    ("EXCLUDED_KEYWORDS", "Слова-исключения товаров (через запятую)"),
]

SUPPORT_FIELDS = [
    ("SUPPORT_EMAIL", "Email поддержки"),
    ("SUPPORT_TELEGRAM", "Telegram поддержки (@username)"),
]


def create_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": expire}, config.ADMIN_SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> str:
    try:
        payload = jwt.decode(token, config.ADMIN_SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return username


def get_csrf_token(request: Request):
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token


async def verify_csrf_token(request: Request):
    token = request.session.get("csrf_token")
    if not token:
        raise HTTPException(status_code=403, detail="CSRF token missing in session")
    
    # Fast path: header token to avoid parsing huge multipart bodies (e.g., promo code uploads)
    header_token = request.headers.get("X-CSRF-Token")
    if header_token and header_token == token:
        return

    form = await request.form()
    submitted_token = form.get("csrf_token") or header_token
    if not submitted_token or submitted_token != token:
        raise HTTPException(status_code=403, detail="CSRF token invalid")


def get_template_context(request: Request, **kwargs):
    """Helper to add common context variables"""
    context = {
        "request": request,
        "csrf_token": get_csrf_token(request),
        "bot": request.state.bot,
        "bots": getattr(request.state, 'bots', []),
    }
    context.update(kwargs)
    return context


# === Bot Switching ===

@app.post("/bot/switch/{bot_id}")
async def switch_bot(request: Request, bot_id: int, user: str = Depends(get_current_user)):
    bot = await get_bot(bot_id)
    if bot:
        request.session["active_bot_id"] = bot_id
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)



# === Bot Management ===

@app.get("/bots/new", response_class=HTMLResponse)
async def new_bot_page(request: Request, user: str = Depends(get_current_user)):
    return templates.TemplateResponse("bots/new.html", get_template_context(request, user=user, title="Добавить бота"))

@app.post("/bots/create", dependencies=[Depends(verify_csrf_token)])
async def create_bot(
    request: Request,
    token: str = Form(...),
    name: str = Form(...),
    type: str = Form(...),
    admin_ids: str = Form(""),
    user: str = Depends(get_current_user)
):
    from database import get_connection
    
    # Get modules from form (checkboxes return list)
    form = await request.form()
    modules = form.getlist('modules')
    
    # Always include registration as required
    if 'registration' not in modules:
        modules.append('registration')
    
    # 1. Validate token (basic check)
    if not token or ":" not in token:
        return templates.TemplateResponse("bots/new.html", get_template_context(
            request, user=user, title="Добавить бота", error="Неверный формат токена", 
            form__token=token, form__name=name, form__type=type, form__admin_ids=admin_ids
        ))
    
    # 2. Parse admin IDs
    parsed_admin_ids = []
    if admin_ids.strip():
        for aid in admin_ids.replace(' ', '').split(','):
            try:
                if aid.strip():
                    parsed_admin_ids.append(int(aid.strip()))
            except ValueError:
                return templates.TemplateResponse("bots/new.html", get_template_context(
                    request, user=user, title="Добавить бота", 
                    error=f"Неверный формат Admin ID: {aid}",
                    form__token=token, form__name=name, form__type=type, form__admin_ids=admin_ids
                ))
    
    # 3. Insert into DB
    try:
        async with get_connection() as db:
            # Check unique token
            exists = await db.fetchval("SELECT 1 FROM bots WHERE token = $1", token)
            if exists:
                return templates.TemplateResponse("bots/new.html", get_template_context(
                    request, user=user, title="Добавить бота", error="Бот с таким токеном уже существует",
                    form__token=token, form__name=name, form__type=type, form__admin_ids=admin_ids
                ))
            
            bot_id = await db.fetchval("""
                INSERT INTO bots (token, name, type, is_active, admin_ids, enabled_modules)
                VALUES ($1, $2, $3, TRUE, $4, $5)
                RETURNING id
            """, token, name, type, parsed_admin_ids, modules)
            
            # Also add admin entries to bot_admins table for easier management
            for aid in parsed_admin_ids:
                await db.execute("""
                    INSERT INTO bot_admins (bot_id, telegram_id, role)
                    VALUES ($1, $2, 'admin')
                    ON CONFLICT DO NOTHING
                """, bot_id, aid)
            
            # Send notification to main process to reload bots
            await db.execute("NOTIFY new_bot")
            
        # Switch to new bot
        request.session["active_bot_id"] = bot_id
        
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        logger.error(f"Failed to create bot: {e}")
        return templates.TemplateResponse("bots/new.html", get_template_context(
            request, user=user, title="Добавить бота", error=f"Ошибка: {e}",
            form__token=token, form__name=name, form__type=type, form__admin_ids=admin_ids
        ))


@app.get("/bots/{bot_id}/edit", response_class=HTMLResponse)
async def edit_bot_page(request: Request, bot_id: int, user: str = Depends(get_current_user), msg: str = None):
    """Bot edit page"""
    from database import get_stats
    
    edit_bot = await get_bot(bot_id)
    if not edit_bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    stats = await get_stats(bot_id)
    
    return templates.TemplateResponse("bots/edit.html", get_template_context(
        request, user=user, title=f"Редактирование: {edit_bot['name']}",
        edit_bot=edit_bot, stats=stats, message=msg
    ))


@app.post("/bots/{bot_id}/update", dependencies=[Depends(verify_csrf_token)])
async def update_bot(
    request: Request, 
    bot_id: int, 
    name: str = Form(...), 
    type: str = Form(...),
    user: str = Depends(get_current_user)
):
    """Update bot basic info"""
    from database import get_connection
    
    async with get_connection() as db:
        await db.execute(
            "UPDATE bots SET name = $2, type = $3 WHERE id = $1",
            bot_id, name, type
        )
    
    return RedirectResponse(
        url=f"/bots/{bot_id}/edit?msg=Изменения+сохранены", 
        status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/bots/{bot_id}/admins", dependencies=[Depends(verify_csrf_token)])
async def update_bot_admins(
    request: Request, 
    bot_id: int, 
    admin_ids: str = Form(""),
    user: str = Depends(get_current_user)
):
    """Update bot admin IDs"""
    from database import update_bot_admins_array, get_connection
    
    # Parse admin IDs
    parsed_ids = []
    if admin_ids.strip():
        for aid in admin_ids.replace(' ', '').split(','):
            try:
                if aid.strip():
                    parsed_ids.append(int(aid.strip()))
            except ValueError:
                pass
    
    await update_bot_admins_array(bot_id, parsed_ids)
    
    # Sync with bot_admins table
    async with get_connection() as db:
        await db.execute("DELETE FROM bot_admins WHERE bot_id = $1", bot_id)
        for aid in parsed_ids:
            await db.execute("""
                INSERT INTO bot_admins (bot_id, telegram_id, role)
                VALUES ($1, $2, 'admin')
                ON CONFLICT DO NOTHING
            """, bot_id, aid)
    
    return RedirectResponse(
        url=f"/bots/{bot_id}/edit?msg=Админы+обновлены",
        status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/bots/{bot_id}/modules", dependencies=[Depends(verify_csrf_token)])
async def update_bot_modules_route(
    request: Request,
    bot_id: int,
    user: str = Depends(get_current_user)
):
    """Update bot enabled modules"""
    from database import update_bot_modules
    
    form = await request.form()
    modules = list(form.getlist('modules'))
    
    # Always include registration
    if 'registration' not in modules:
        modules.append('registration')
    
    await update_bot_modules(bot_id, modules)
    
    return RedirectResponse(
        url=f"/bots/{bot_id}/edit?msg=Модули+обновлены",
        status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/bots/{bot_id}/archive", dependencies=[Depends(verify_csrf_token)])
async def archive_bot_route(
    request: Request,
    bot_id: int,
    user: str = Depends(get_current_user)
):
    """Archive a bot (soft delete)"""
    from database import archive_bot
    
    await archive_bot(bot_id, user)
    
    # Clear active bot if it was archived
    if request.session.get("active_bot_id") == bot_id:
        request.session.pop("active_bot_id", None)
    
    return RedirectResponse(url="/?msg=Бот+архивирован", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/bots/{bot_id}/migrate", response_class=HTMLResponse)
async def migrate_bot_page(request: Request, bot_id: int, user: str = Depends(get_current_user)):
    """Migration page"""
    from database import get_all_bots, get_stats
    
    source_bot = await get_bot(bot_id)
    if not source_bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    # Get all other bots as potential targets
    all_bots = await get_all_bots()
    target_bots = [b for b in all_bots if b['id'] != bot_id]
    
    stats = await get_stats(bot_id)
    
    return templates.TemplateResponse("bots/migrate.html", get_template_context(
        request, user=user, title=f"Миграция: {source_bot['name']}",
        source_bot=source_bot, target_bots=target_bots, stats=stats
    ))


@app.post("/bots/{bot_id}/migrate", dependencies=[Depends(verify_csrf_token)])
async def migrate_bot_route(
    request: Request,
    bot_id: int,
    target_bot_id: int = Form(...),
    user: str = Depends(get_current_user)
):
    """Execute migration"""
    from database import migrate_bot_data
    
    result = await migrate_bot_data(bot_id, target_bot_id, user)
    
    return RedirectResponse(
        url=f"/bots/{target_bot_id}/edit?msg=Мигрировано+{result['users_migrated']}+пользователей",
        status_code=status.HTTP_303_SEE_OTHER
    )

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "csrf_token": get_csrf_token(request)})


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    if form.get("username") == config.ADMIN_PANEL_USER and form.get("password") == config.ADMIN_PANEL_PASSWORD:
        token = create_token(form.get("username"))
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie("access_token", token, httponly=True, max_age=TOKEN_EXPIRE_HOURS * 3600)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response


# === Dashboard ===

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(get_current_user)):
    bot = request.state.bot
    if not bot:
        return templates.TemplateResponse("dashboard.html", get_template_context(
            request, user=user, error="No active bot",
            stats={}, participants=0, daily_stats=[], recent_campaigns=[], title="Dashboard"
        ))

    bot_id = bot['id']
    stats = await get_stats(bot_id)
    participants = await get_participants_count(bot_id)
    daily_stats = await get_stats_by_days(bot_id, 14)
    # Convert dates
    for stat in daily_stats:
        if 'day' in stat and isinstance(stat['day'], (datetime, date)):
            stat['day'] = stat['day'].isoformat()
            
    recent_campaigns = await get_recent_campaigns(bot_id, 5)
    
    return templates.TemplateResponse("dashboard.html", get_template_context(
        request, user=user, stats=stats, participants=participants,
        daily_stats=daily_stats, recent_campaigns=recent_campaigns,
        title="Dashboard"
    ))


# === Statistics API ===

@app.get("/api/stats/daily")
async def api_daily_stats(request: Request, days: int = 14, user: str = Depends(get_current_user)):
    bot = request.state.bot
    if not bot: return JSONResponse({})
    
    data = await get_stats_by_days(bot['id'], days)
    return JSONResponse({
        "labels": [str(d['day']) for d in data],
        "users": [d['users'] for d in data],
        "receipts": [d['receipts'] for d in data]
    })


# === Settings ===

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
    from utils.config_manager import config_manager
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    if not config_manager._initialized:
        await config_manager.load()
    
    bot_id = bot['id']
    
    # We no longer read .env for dynamic settings, purely from DB per bot
    # But for backward compatibility or defaults, we can check config.py
    
    promo_fields = []
    for key, label in PROMO_FIELDS:
        val = config_manager.get_setting(key, getattr(config, key, ""), bot_id)
        promo_fields.append((key, label, val))
    
    db_settings = await config_manager.get_all_settings(bot_id)
    
    return templates.TemplateResponse("settings/index.html", get_template_context(
        request, user=user, title="Настройки",
        promo_fields=promo_fields, db_settings=db_settings,
        updated=updated
    ))


@app.post("/settings/update", dependencies=[Depends(verify_csrf_token)])
async def update_setting(request: Request, key: str = Form(...), value: str = Form(...), user: str = Depends(get_current_user)):
    from utils.config_manager import config_manager
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    await config_manager.set_setting(key, value, bot['id'])
    return RedirectResponse(url="/settings?updated=1", status_code=status.HTTP_303_SEE_OTHER)


# === Support Settings ===

@app.get("/settings/support", response_class=HTMLResponse)
async def support_settings_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
    from utils.config_manager import config_manager
    bot = request.state.bot
    if not bot: return RedirectResponse("/")
    
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


@app.post("/settings/support/update", dependencies=[Depends(verify_csrf_token)])
async def update_support_setting(request: Request, key: str = Form(...), value: str = Form(...), user: str = Depends(get_current_user)):
    from utils.config_manager import config_manager
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    await config_manager.set_setting(key, value, bot['id'])
    return RedirectResponse(url="/settings/support?updated=1", status_code=status.HTTP_303_SEE_OTHER)


# === Messages ===

@app.get("/settings/messages", response_class=HTMLResponse)
async def messages_page(request: Request, user: str = Depends(get_current_user), updated: str = None):
    from utils.config_manager import config_manager
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    if not config_manager._initialized:
        await config_manager.load()
    
    messages = await config_manager.get_all_messages(bot['id'])
    
    # Format: (key, description, default_text)
    default_messages = [
        # Registration
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
        
        # Receipts
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
        
        # Promo codes
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
        
        # Profile & history
        ("profile", "Профиль пользователя (кнопка 👤)",
         "👤 Ваш профиль\n\nИмя: {name}\nТелефон: {phone}\n\n📊 Чеков: {total}\n🎫 Билетов: {tickets}"),
        ("no_receipts", "У пользователя нет чеков",
         "📋 У вас пока нет чеков\n\nНажмите «🧾 Загрузить чек»"),
        
        # FAQ
        ("faq_how", "FAQ: Как участвовать",
         "🎯 Как участвовать?\n\n1. Купите акционные товары\n2. Сфотографируйте QR-код\n3. Загрузите в бот"),
        ("faq_win", "FAQ: Как узнать о выигрыше",
         "🏆 Как узнать о выигрыше?\n\nМы пришлём сообщение в этот бот!"),
        
        # Support
        ("support_msg", "Сообщение при нажатии 🆘 Поддержка",
         "🆘 Нужна помощь?\n\nНапишите нам!"),
    ]
    
    return templates.TemplateResponse("settings/messages.html", get_template_context(
        request, user=user, title="Тексты сообщений",
        messages=messages, default_messages=default_messages,
        updated=updated
    ))


@app.post("/settings/messages/update", dependencies=[Depends(verify_csrf_token)])
async def update_message(request: Request, key: str = Form(...), text: str = Form(...), user: str = Depends(get_current_user)):
    from utils.config_manager import config_manager
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    await config_manager.set_message(key, text, bot['id'])
    return RedirectResponse(url="/settings/messages?updated=1", status_code=status.HTTP_303_SEE_OTHER)


# === Users list ===

@app.get("/users", response_class=HTMLResponse)
async def users_list(request: Request, user: str = Depends(get_current_user), page: int = 1, q: str = None):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")
    
    if q:
        users = await search_users(q, bot['id'])
        total = len(users)
        total_pages = 1
    else:
        users = await get_users_paginated(bot['id'], page=page, per_page=50)
        total = await get_total_users_count(bot['id'])
        total_pages = (total + 49) // 50
    
    return templates.TemplateResponse("users/list.html", get_template_context(
        request, user=user, users=users,
        page=page, total_pages=total_pages, total=total,
        search_query=q or "", title="Пользователи"
    ))


# === User Detail ===

@app.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: int, user: str = Depends(get_current_user), msg: str = None):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")
    
    # We should verify user belongs to bot, but get_user_detail fetches by ID.
    # We can check bot_id in result.
    user_data = await get_user_detail(user_id)
    if not user_data or user_data['bot_id'] != bot['id']:
        raise HTTPException(status_code=404, detail="User not found")
    
    receipts = await get_user_receipts_detailed(user_id, limit=50)
    
    return templates.TemplateResponse("users/detail.html", get_template_context(
        request, user=user, user_data=user_data,
        receipts=receipts, title=f"Пользователь #{user_id}",
        message=msg
    ))


@app.post("/users/{user_id}/message", dependencies=[Depends(verify_csrf_token)])
async def send_user_message(request: Request, user_id: int, text: str = Form(None), photo: UploadFile = File(None), user: str = Depends(get_current_user)):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")
    
    user_data = await get_user_detail(user_id)
    if not user_data or user_data['bot_id'] != bot['id']:
        raise HTTPException(status_code=404, detail="User not found")

    content = {}
    if photo and photo.filename:
        ext = Path(photo.filename).suffix or ".jpg"
        filename = f"{uuid.uuid4()}{ext}"
        filepath = UPLOADS_DIR / filename
        async with aiofiles.open(filepath, 'wb') as f:
            while chunk := await photo.read(1024 * 1024):
                await f.write(chunk)
        content["photo_path"] = str(filepath)
        content["caption"] = text
    elif text:
        content["text"] = text
    else:
        return RedirectResponse(url=f"/users/{user_id}?msg=error_empty", status_code=status.HTTP_303_SEE_OTHER)
    
    content["target_user_id"] = user_data['telegram_id']
    content["user_id"] = user_data['telegram_id'] # execute_single_message expects user_id
    
    await add_campaign("message", content, bot['id'])
    
    return RedirectResponse(url=f"/users/{user_id}?msg=sent", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/users/{user_id}/add-receipt", dependencies=[Depends(verify_csrf_token)])
async def add_user_receipt(request: Request, user_id: int, user: str = Depends(get_current_user)):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    user_data = await get_user_detail(user_id)
    if not user_data or user_data['bot_id'] != bot['id']:
        raise HTTPException(status_code=404, detail="User not found")
    
    ts = int(time.time())
    uid = str(uuid.uuid4())[:8]
    
    await add_receipt(
        user_id=user_id, status="valid",
        data={"manual": True, "admin": user, "source": "web_panel"},
        bot_id=bot['id'],
        fiscal_drive_number="MANUAL",
        fiscal_document_number=f"MANUAL_{ts}_{uid}",
        fiscal_sign=f"MANUAL_{user_id}_{ts}",
        total_sum=0, raw_qr="manual_web",
        product_name="Ручное добавление (веб)"
    )
    
    return RedirectResponse(url=f"/users/{user_id}?msg=receipt_added", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/users/{user_id}/block", dependencies=[Depends(verify_csrf_token)])
async def toggle_user_block(request: Request, user_id: int, user: str = Depends(get_current_user)):
    user_data = await get_user_detail(user_id)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    new_status = not user_data.get('is_blocked', False)
    await block_user(user_id, new_status)
    return RedirectResponse(url=f"/users/{user_id}?msg={'blocked' if new_status else 'unblocked'}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/users/{user_id}/update", dependencies=[Depends(verify_csrf_token)])
async def update_user_profile(request: Request, user_id: int, full_name: str = Form(None), phone: str = Form(None), username: str = Form(None), user: str = Depends(get_current_user)):
    from database import update_user_fields
    bot = request.state.bot
    if not bot:
        return RedirectResponse("/")

    user_data = await get_user_detail(user_id)
    if not user_data or user_data['bot_id'] != bot['id']:
        raise HTTPException(status_code=404, detail="User not found")

    full_name_clean = full_name.strip() if full_name else None
    phone_clean = phone.strip() if phone else None
    username_clean = username.strip().lstrip("@") if username else None

    await update_user_fields(
        user_id,
        full_name=full_name_clean or user_data.get("full_name"),
        phone=phone_clean or user_data.get("phone"),
        username=username_clean if username is not None else user_data.get("username"),
    )

    return RedirectResponse(url=f"/users/{user_id}?msg=updated", status_code=status.HTTP_303_SEE_OTHER)


# === Receipts ===

@app.get("/receipts", response_class=HTMLResponse)
async def receipts_list(request: Request, user: str = Depends(get_current_user), page: int = 1):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")
    if bot.get("type") != "receipt":
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    receipts = await get_all_receipts_paginated(bot['id'], page=page, per_page=50)
    total = await get_total_receipts_count(bot['id'])
    total_pages = (total + 49) // 50
    return templates.TemplateResponse("receipts/list.html", get_template_context(
        request, user=user, receipts=receipts,
        page=page, total_pages=total_pages, total=total,
        title="Чеки"
    ))


# === Winners ===

@app.get("/winners", response_class=HTMLResponse)
async def winners_list(request: Request, user: str = Depends(get_current_user)):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    raffles = await get_recent_raffles_with_winners(bot['id'], limit=10)
    return templates.TemplateResponse("winners/list.html", get_template_context(
        request, user=user, raffles=raffles, title="Победители"
    ))


# === Broadcast ===

@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, user: str = Depends(get_current_user), created: str = None):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    total_users = await get_total_users_count(bot['id'])
    recent = await get_recent_campaigns(bot['id'], 10)
    broadcasts = [c for c in recent if c['type'] == 'broadcast']
    
    return templates.TemplateResponse("broadcast/index.html", get_template_context(
        request, user=user, title="Рассылка",
        total_users=total_users, broadcasts=broadcasts,
        created=created
    ))


@app.post("/broadcast/create", dependencies=[Depends(verify_csrf_token)])
async def create_broadcast(request: Request, text: str = Form(None), photo: UploadFile = File(None), scheduled_for: str = Form(None), user: str = Depends(get_current_user)):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    content = {}
    if photo and photo.filename:
        ext = Path(photo.filename).suffix or ".jpg"
        filename = f"{uuid.uuid4()}{ext}"
        filepath = UPLOADS_DIR / filename
        async with aiofiles.open(filepath, 'wb') as f:
            while chunk := await photo.read(1024 * 1024):
                await f.write(chunk)
        content["photo_path"] = str(filepath)
        content["caption"] = text
    elif text:
        content["text"] = text
    else:
        raise HTTPException(status_code=400, detail="Message required")
    
    schedule_dt = None
    if scheduled_for and scheduled_for.strip():
        schedule_dt = config.parse_scheduled_time(scheduled_for)
    
    campaign_id = await add_campaign("broadcast", content, bot['id'], schedule_dt)
    return RedirectResponse(url=f"/broadcast?created={campaign_id}", status_code=status.HTTP_303_SEE_OTHER)


# === All Campaigns ===

@app.get("/campaigns", response_class=HTMLResponse)
async def campaigns_list(request: Request, user: str = Depends(get_current_user), page: int = 1):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")
    
    # We reuse get_recent_campaigns but maybe we need pagination?
    # For now let's just show top 50
    campaigns = await get_recent_campaigns(bot['id'], limit=50)
    
    return templates.TemplateResponse("campaigns/list.html", get_template_context(
        request, user=user, campaigns=campaigns,
        title="Кампании"
    ))


# === Promo Codes ===

@app.get("/codes", response_class=HTMLResponse)
async def codes_list(request: Request, user: str = Depends(get_current_user), page: int = 1):
    from database import get_promo_stats, get_promo_codes_paginated
    bot = request.state.bot
    if not bot: return RedirectResponse("/")
    if bot.get("type") != "promo":
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    
    stats = await get_promo_stats(bot['id'])
    codes = await get_promo_codes_paginated(bot['id'], limit=50, offset=(page-1)*50)
    
    return templates.TemplateResponse("codes/list.html", get_template_context(
        request, user=user, title="Промокоды",
        stats=stats, codes=codes
    ))

@app.post("/codes/upload", dependencies=[Depends(verify_csrf_token)])
async def upload_codes(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...), user: str = Depends(get_current_user)):
    from admin_panel.utils.importer import process_promo_import
    from database import create_job
    bot = request.state.bot
    if not bot or bot.get("type") != "promo":
        return JSONResponse({"status": "error", "message": "Bot not found or unsupported"}, status_code=400)
    
    logger.info(f"[codes/upload] start bot={bot['id']} filename={file.filename} content_type={file.content_type}")
    
    # Save to temp file
    try:
        temp_dir = UPLOADS_DIR / "temp_imports"
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"import_{bot['id']}_{int(time.time())}_{uuid.uuid4()}.txt"
        
        async with aiofiles.open(temp_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024):  # Read in chunks
                await out_file.write(content)
        
        file_size_mb = round(temp_path.stat().st_size / 1024 / 1024, 2)
        logger.info(f"[codes/upload] saved file {temp_path} size={file_size_mb}MB bot={bot['id']}")
        
        # Create job immediately to show in UI
        job_id = await create_job(bot['id'], 'import_promo', {"file": temp_path.name, "size_mb": file_size_mb})
        
        # Schedule background task
        background_tasks.add_task(process_promo_import, str(temp_path), bot['id'], job_id)
        
        return JSONResponse({
            "status": "queued", 
            "message": f"Файл загружен ({file_size_mb} MB). Импорт #{job_id} запущен в фоне.",
            "job_id": job_id
        })
        
    except Exception as e:
        logger.error(f"[codes/upload] error: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)



@app.get("/api/jobs/active")
async def get_active_jobs_api(request: Request, user: str = Depends(get_current_user)):
    from database import get_active_jobs
    bot = request.state.bot
    if not bot: return JSONResponse([])
    
    jobs = await get_active_jobs(bot['id'])
    # Convert records to dict and handle datetimes
    return JSONResponse([
        {
            "id": j['id'],
            "type": j['type'],
            "status": j['status'],
            "progress": j['progress'],
            "details": json.loads(j['details']) if isinstance(j['details'], str) else j['details'],
            "created_at": j['created_at'].isoformat() if j['created_at'] else None
        } for j in jobs
    ])

@app.get("/api/jobs/{job_id}")
async def get_job_api(job_id: int, request: Request, user: str = Depends(get_current_user)):
    from database import get_job
    bot = request.state.bot
    if not bot:
        return JSONResponse({"detail": "Bot not found"}, status_code=400)

    job = await get_job(job_id, bot['id'])
    if not job:
        return JSONResponse({"detail": "Job not found"}, status_code=404)

    details = json.loads(job['details']) if isinstance(job['details'], str) else job['details']
    return JSONResponse({
        "id": job['id'],
        "type": job['type'],
        "status": job['status'],
        "progress": job['progress'],
        "details": details,
        "created_at": job['created_at'].isoformat() if job['created_at'] else None,
        "updated_at": job['updated_at'].isoformat() if job['updated_at'] else None,
    })

# === Raffle ===

@app.get("/raffle", response_class=HTMLResponse)
async def raffle_page(request: Request, user: str = Depends(get_current_user), created: str = None):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    participants = await get_participants_count(bot['id'])
    total_tickets = await get_total_tickets_count(bot['id'])
    recent_raffles = await get_recent_raffles_with_winners(bot['id'], limit=5)
    
    return templates.TemplateResponse("raffle/index.html", get_template_context(
        request, user=user, title="Розыгрыш",
        participants=participants, total_tickets=total_tickets,
        recent_raffles=recent_raffles, created=created
    ))


@app.post("/raffle/create", dependencies=[Depends(verify_csrf_token)])
async def create_raffle(request: Request, prize_name: str = Form(...), winner_count: int = Form(...), win_text: str = Form(None), win_photo: UploadFile = File(None), lose_text: str = Form(None), lose_photo: UploadFile = File(None), scheduled_for: str = Form(None), user: str = Depends(get_current_user)):
    bot = request.state.bot
    if not bot: return RedirectResponse("/")

    participants = await get_participants_count(bot['id'])
    if winner_count < 1 or winner_count > participants:
        # Avoid error if 0 participants, just warn?
        # raise HTTPException(status_code=400, detail=f"Winner count must be 1-{participants}")
        pass
    
    win_msg = {}
    if win_photo and win_photo.filename:
        ext = Path(win_photo.filename).suffix or ".jpg"
        filename = f"win_{uuid.uuid4()}{ext}"
        filepath = UPLOADS_DIR / filename
        async with aiofiles.open(filepath, 'wb') as f:
            while content := await win_photo.read(1024 * 1024):
                await f.write(content)
        win_msg["photo_path"] = str(filepath)
        win_msg["caption"] = win_text
    elif win_text:
        win_msg["text"] = win_text
    else:
        win_msg["text"] = f"🎉 Поздравляем! Вы выиграли: {prize_name}!"
    
    lose_msg = {}
    if lose_photo and lose_photo.filename:
        ext = Path(lose_photo.filename).suffix or ".jpg"
        filename = f"lose_{uuid.uuid4()}{ext}"
        filepath = UPLOADS_DIR / filename
        async with aiofiles.open(filepath, 'wb') as f:
            while content := await lose_photo.read(1024 * 1024):
                await f.write(content)
        lose_msg["photo_path"] = str(filepath)
        lose_msg["caption"] = lose_text
    elif lose_text:
        lose_msg["text"] = lose_text
    
    content = {
        "prize": prize_name,
        "prize_name": prize_name,
        "count": winner_count,
        "win_msg": win_msg,
        "lose_msg": lose_msg
    }
    
    schedule_dt = None
    if scheduled_for and scheduled_for.strip():
        schedule_dt = config.parse_scheduled_time(scheduled_for)
    
    campaign_id = await add_campaign("raffle", content, bot['id'], schedule_dt)
    return RedirectResponse(url=f"/raffle?created={campaign_id}", status_code=status.HTTP_303_SEE_OTHER)


# === Backups ===
@app.get("/backups", response_class=HTMLResponse)
async def backups_list(request: Request, user: str = Depends(get_current_user)):
    # Backups are global functionality usually, or per-bot? 
    # Current backup script dumps database. So it's global.
    from pathlib import Path
    import os
    import shutil
    
    backup_dir = Path("/var/backups/admin-bots-platform")
    if not backup_dir.exists():
        backup_dir = BASE_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)

    backups = []
    if backup_dir.exists():
        for file in sorted(backup_dir.glob("backup_*.sql.gz"), reverse=True):
            stat = file.stat()
            backups.append({
                "filename": file.name,
                "size": stat.st_size,
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "created": datetime.fromtimestamp(stat.st_mtime),
                "path": str(file)
            })
    
    total_size_mb = sum(b['size_mb'] for b in backups)
    disk_free_mb = round(shutil.disk_usage(backup_dir).free / 1024 / 1024, 2)
    
    return templates.TemplateResponse("backups/list.html", get_template_context(
        request, user=user, title="Резервные копии",
        backups=backups, total_size_mb=total_size_mb, disk_free_mb=disk_free_mb
    ))


@app.post("/backups/create", dependencies=[Depends(verify_csrf_token)])
async def create_backup_handler(request: Request, user: str = Depends(get_current_user)):
    """Trigger backup script"""
    import subprocess
    
    # Determine backup dir (same logic as GET)
    backup_dir = Path("/var/backups/admin-bots-platform")
    if not backup_dir.exists() or not os.access(str(backup_dir), os.W_OK):
        backup_dir = BASE_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)
    
    script_path = BASE_DIR / "scripts" / "backup.sh"
    
    try:
        # Run script with backup_dir as argument
        # Use 'bash' explicitly
        result = subprocess.run(
            ["bash", str(script_path), str(backup_dir)],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"Backup created: {result.stdout}")
        return RedirectResponse(url="/backups?created=1", status_code=status.HTTP_303_SEE_OTHER)
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Backup failed: {e.stderr}")
        return RedirectResponse(url=f"/backups?error=1", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.critical(f"Backup execution error: {e}")
        return RedirectResponse(url=f"/backups?error=1", status_code=status.HTTP_303_SEE_OTHER)


# === Modules Management ===

@app.get("/modules", response_class=HTMLResponse)
async def modules_list(request: Request, user: str = Depends(get_current_user)):
    """Module management page"""
    bot = request.state.bot
    if not bot:
        return RedirectResponse("/")
    
    from modules import module_loader
    from database import get_connection
    
    # Get all registered modules
    all_modules = module_loader.get_all_modules()
    
    # Get enabled status from database
    async with get_connection() as db:
        rows = await db.fetch("""
            SELECT module_name, is_enabled, settings 
            FROM module_settings 
            WHERE bot_id = $1
        """, bot['id'])
        
        enabled_map = {r['module_name']: r['is_enabled'] for r in rows}
    
    # Build module list with status
    modules_data = []
    for mod in all_modules:
        is_enabled = enabled_map.get(mod.name, mod.default_enabled)
        modules_data.append({
            "name": mod.name,
            "version": mod.version,
            "description": mod.description,
            "is_enabled": is_enabled,
            "dependencies": mod.dependencies,
        })
    
    return templates.TemplateResponse("modules/list.html", get_template_context(
        request, user=user, title="Модули",
        modules=modules_data
    ))


@app.post("/modules/toggle/{module_name}", dependencies=[Depends(verify_csrf_token)])
async def toggle_module(request: Request, module_name: str, user: str = Depends(get_current_user)):
    """Toggle module enabled/disabled for current bot"""
    bot = request.state.bot
    if not bot:
        return RedirectResponse("/")
    
    from modules import module_loader
    
    module = module_loader.get_module(module_name)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    # Check current status and toggle
    is_enabled = module_loader.is_enabled(bot['id'], module_name)
    
    if is_enabled:
        await module_loader.disable_module(bot['id'], module_name)
    else:
        await module_loader.enable_module(bot['id'], module_name)
    
    return RedirectResponse(url="/modules", status_code=status.HTTP_303_SEE_OTHER)
