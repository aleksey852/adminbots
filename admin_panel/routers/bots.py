"""Bots management router: CRUD, export, delete"""
from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, date
from typing import Dict
import logging
import uuid
import json

import config
from database.panel_db import (
    get_bot_by_id, get_bot_by_token, register_bot, get_panel_connection,
    create_bot_database
)
from database.bot_db import bot_db_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bots", tags=["bots"])

# Will be set by setup_routes
templates = None
get_current_user = None
require_superadmin = None
verify_csrf_token = None
get_template_context = None


def setup_routes(
    app_templates: Jinja2Templates,
    auth_get_current_user,
    auth_require_superadmin,
    auth_verify_csrf_token,
    context_helper
):
    """Setup routes with dependencies"""
    global templates, get_current_user, require_superadmin, verify_csrf_token, get_template_context
    templates = app_templates
    get_current_user = auth_get_current_user
    require_superadmin = auth_require_superadmin
    verify_csrf_token = auth_verify_csrf_token
    get_template_context = context_helper

    @router.post("/switch/{bot_id}")
    async def switch_bot(request: Request, bot_id: int, user: str = Depends(get_current_user)):
        bot = await get_bot_by_id(bot_id)
        if bot:
            request.session["active_bot_id"] = bot_id
        referer = request.headers.get("referer", "/")
        return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)

    @router.get("/new", response_class=HTMLResponse)
    async def new_bot_page(request: Request, user: Dict = Depends(require_superadmin)):
        return templates.TemplateResponse("bots/new.html", get_template_context(request, user=user, title="Добавить бота"))

    @router.post("/create", dependencies=[Depends(verify_csrf_token)])
    async def create_bot(
        request: Request, token: str = Form(...), name: str = Form(...),
        type: str = Form(...), admin_ids: str = Form(""), user: Dict = Depends(require_superadmin)
    ):
        import re
        from database.panel_db import get_bot_by_token, register_bot, create_bot_database, get_panel_connection
        
        modules = (await request.form()).getlist('modules')
        if 'registration' not in modules: modules.append('registration')
        
        if not token or ":" not in token:
            return templates.TemplateResponse("bots/new.html", get_template_context(request, user=user, title="Новый бот", error="Bad token", form__token=token, form__name=name))
        
        try:
            if await get_bot_by_token(token):
                return templates.TemplateResponse("bots/new.html", get_template_context(request, user=user, title="Новый бот", error="Exists", form__token=token))
            
            p_ids = [int(x.strip()) for x in admin_ids.split(',') if x.strip().isdigit()]
            db_url = await create_bot_database(f"bot_{re.sub(r'[^a-z0-9_]', '', name.lower())[:20]}_{uuid.uuid4().hex[:6]}", config.DATABASE_URL)
            
            bid = await register_bot(token=token, name=name, bot_type=type, database_url=db_url, admin_ids=p_ids)
            bot_db_manager.register(bid, db_url)
            await bot_db_manager.connect(bid)
            
            async with get_panel_connection() as db: await db.execute("NOTIFY new_bot")
            request.session["active_bot_id"] = bid
            return RedirectResponse("/", 303)
        except Exception as e:
            logger.error(f"Bot creation failed: {e}")
            return templates.TemplateResponse("bots/new.html", get_template_context(request, user=user, title="Новый бот", error=str(e)))

    @router.get("/{bot_id}/edit", response_class=HTMLResponse)
    async def edit_bot_page(request: Request, bot_id: int, user: Dict = Depends(require_superadmin), msg: str = None):
        from database.bot_methods import get_stats, bot_db_context
        from utils.config_manager import config_manager
        
        bot = await get_bot_by_id(bot_id)
        if not bot: raise HTTPException(404, "Bot not found")
        
        if not bot_db_manager.get(bot_id):
            bot_db_manager.register(bot_id, bot['database_url'])
            await bot_db_manager.connect(bot_id)
        
        if not config_manager._initialized: await config_manager.load()
        
        # Fetch subscription settings
        SUBSCRIPTION_FIELDS = [
            ("SUBSCRIPTION_REQUIRED", "Требовать подписку на канал"),
            ("SUBSCRIPTION_CHANNEL_ID", "ID канала (напр. -1001234567890)"),
            ("SUBSCRIPTION_CHANNEL_URL", "Ссылка на канал"),
        ]
        defaults = {"SUBSCRIPTION_REQUIRED": "false", "SUBSCRIPTION_CHANNEL_ID": "", "SUBSCRIPTION_CHANNEL_URL": ""}
        sub_settings = [(k, l, config_manager.get_setting(k, defaults.get(k, ""), bot_id)) for k, l in SUBSCRIPTION_FIELDS]

        async with bot_db_context(bot_id): stats = await get_stats()
        return templates.TemplateResponse("bots/edit.html", get_template_context(
            request, user=user, title=f"Бот: {bot['name']}", edit_bot=bot, stats=stats, message=msg,
            subscription_settings=sub_settings
        ))

    @router.post("/{bot_id}/subscription", dependencies=[Depends(verify_csrf_token)])
    async def update_bot_subscription(
        request: Request, bot_id: int, 
        SUBSCRIPTION_REQUIRED: str = Form("false"),
        SUBSCRIPTION_CHANNEL_ID: str = Form(""),
        SUBSCRIPTION_CHANNEL_URL: str = Form("")
    ):
        from utils.config_manager import config_manager
        
        await config_manager.set_setting('SUBSCRIPTION_REQUIRED', SUBSCRIPTION_REQUIRED, bot_id)
        await config_manager.set_setting('SUBSCRIPTION_CHANNEL_ID', SUBSCRIPTION_CHANNEL_ID, bot_id)
        await config_manager.set_setting('SUBSCRIPTION_CHANNEL_URL', SUBSCRIPTION_CHANNEL_URL, bot_id)
        
        return RedirectResponse(f"/bots/{bot_id}/edit?msg=Subscription+updated", 303)

    @router.post("/{bot_id}/update", dependencies=[Depends(verify_csrf_token)])
    async def update_bot_route(request: Request, bot_id: int, name: str = Form(...), type: str = Form(...)):
        from database.panel_db import get_panel_connection
        async with get_panel_connection() as db:
            await db.execute("UPDATE bot_registry SET name = $2, type = $3 WHERE id = $1", bot_id, name, type)
        return RedirectResponse(f"/bots/{bot_id}/edit?msg=Updated", 303)

    @router.post("/{bot_id}/admins", dependencies=[Depends(verify_csrf_token)])
    async def update_bot_admins(request: Request, bot_id: int, admin_ids: str = Form("")):
        from database.panel_db import update_bot
        p_ids = [int(x.strip()) for x in admin_ids.split(',') if x.strip().isdigit()]
        await update_bot(bot_id, admin_ids=p_ids)
        return RedirectResponse(f"/bots/{bot_id}/edit?msg=Admins+updated", 303)

    @router.get("/{bot_id}/modules", response_class=HTMLResponse)
    async def bot_modules_page(request: Request, bot_id: int, user: Dict = Depends(require_superadmin)):
        bot = await get_bot_by_id(bot_id)
        if not bot: raise HTTPException(404, "Bot not found")
        
        from modules.base import module_loader
        # Get module objects to show descriptions
        modules = []
        for name, mod in module_loader.modules.items():
             modules.append({"name": name, "description": mod.description})
        
        # Sort: core/registration first, then others
        modules.sort(key=lambda x: 0 if x['name'] in ('core', 'registration') else 1)
        
        return templates.TemplateResponse("bots/modules.html", get_template_context(
            request, user=user, title=f"Модули: {bot['name']}", bot=bot, available_modules=modules
        ))

    @router.post("/{bot_id}/modules", dependencies=[Depends(verify_csrf_token)])
    async def update_bot_modules(request: Request, bot_id: int):
        from database.panel_db import update_bot
        form = await request.form()
        modules = list(form.getlist('modules'))
        # Ensure required modules are always included
        if 'registration' not in modules:
            modules.append('registration')
        if 'core' not in modules:
            modules.append('core')
        await update_bot(bot_id, enabled_modules=modules)
        return RedirectResponse(f"/bots/{bot_id}/edit?msg=Modules+updated", 303)

    @router.post("/{bot_id}/delete", dependencies=[Depends(verify_csrf_token)])
    async def delete_bot_permanently(request: Request, bot_id: int, confirm: str = Form(...), user: Dict = Depends(require_superadmin)):
        from database.panel_db import delete_bot_registry
        bot = await get_bot_by_id(bot_id)
        if not bot or confirm != bot['name']: 
            return RedirectResponse(f"/bots/{bot_id}/edit?msg=Bad+confirm", 303)
        
        try:
            db = bot_db_manager.get(bot_id)
            if db:
                async with db.get_connection() as conn:
                    # Use transaction to ensure atomicity
                    async with conn.conn.transaction():
                        # Use TRUNCATE CASCADE for faster deletion with FK handling
                        tables = ["winners", "promo_codes", "receipts", "campaigns", 
                                  "messages", "settings", "manual_tickets", "broadcast_progress", "jobs"]
                        for t in tables:
                            await conn.execute(f"TRUNCATE {t} CASCADE")
                        # Users last (other tables depend on it)
                        await conn.execute("TRUNCATE users CASCADE")
                await bot_db_manager.disconnect(bot_id)
            await delete_bot_registry(bot_id)
            if request.session.get("active_bot_id") == bot_id: 
                request.session.pop("active_bot_id", None)
            return RedirectResponse("/?msg=Deleted", 303)
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return RedirectResponse(f"/bots/{bot_id}/edit?msg=Error", 303)

    @router.post("/{bot_id}/restart", dependencies=[Depends(verify_csrf_token)])
    async def restart_bot_route(request: Request, bot_id: int):
        from database.panel_db import get_panel_connection
        from utils.bot_middleware import clear_modules_cache
        
        # 1. Clear middleware cache in THIS process (Admin Panel)
        clear_modules_cache(bot_id)
        
        try:
            # 2. Notify Bot Process to restart the bot
            async with get_panel_connection() as db:
                await db.execute("SELECT pg_notify('restart_bot', $1)", str(bot_id))
                
            return RedirectResponse(f"/bots/{bot_id}/edit?msg=Restart+signal+sent", 303)
        except Exception as e:
            logger.error(f"Failed to send restart signal: {e}")
            return RedirectResponse(f"/bots/{bot_id}/edit?error=Signal+failed", 303)

    return router
