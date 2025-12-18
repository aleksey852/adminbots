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
        request: Request,
        token: str = Form(...),
        name: str = Form(...),
        type: str = Form(...),
        admin_ids: str = Form(""),
        user: Dict = Depends(require_superadmin)
    ):
        import re
        
        # Get modules from form
        form = await request.form()
        modules = form.getlist('modules')
        
        if 'registration' not in modules:
            modules.append('registration')
        
        # Validate token
        if not token or ":" not in token:
            return templates.TemplateResponse("bots/new.html", get_template_context(
                request, user=user, title="Добавить бота", error="Неверный формат токена",
                form__token=token, form__name=name, form__type=type, form__admin_ids=admin_ids
            ))
        
        # Parse admin IDs
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
        
        try:
            # Check if bot exists
            existing = await get_bot_by_token(token)
            if existing:
                return templates.TemplateResponse("bots/new.html", get_template_context(
                    request, user=user, title="Добавить бота", error="Бот с таким токеном уже существует",
                    form__token=token, form__name=name, form__type=type, form__admin_ids=admin_ids
                ))
            
            # Create database
            safe_name = re.sub(r'[^a-z0-9_]', '', name.lower().replace(' ', '_'))[:30]
            db_name = f"bot_{safe_name}_{uuid.uuid4().hex[:8]}"
            
            database_url = await create_bot_database(db_name, config.DATABASE_URL)
            
            # Register bot
            bot_id = await register_bot(
                token=token,
                name=name,
                bot_type=type,
                database_url=database_url,
                admin_ids=parsed_admin_ids
            )
            
            # Initialize bot's database
            bot_db_manager.register(bot_id, database_url)
            await bot_db_manager.connect(bot_id)
            
            # Notify main process
            async with get_panel_connection() as db:
                await db.execute("NOTIFY new_bot")
            
            request.session["active_bot_id"] = bot_id
            logger.info(f"Created bot {bot_id} ({name}) with database {db_name}")
            
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
            
        except Exception as e:
            logger.error(f"Failed to create bot: {e}")
            return templates.TemplateResponse("bots/new.html", get_template_context(
                request, user=user, title="Добавить бота", error=f"Ошибка: {e}",
                form__token=token, form__name=name, form__type=type, form__admin_ids=admin_ids
            ))

    @router.get("/{bot_id}/edit", response_class=HTMLResponse)
    async def edit_bot_page(request: Request, bot_id: int, user: Dict = Depends(require_superadmin), msg: str = None):
        from database.methods import get_stats
        
        edit_bot = await get_bot_by_id(bot_id)
        if not edit_bot:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        stats = await get_stats(bot_id)
        
        return templates.TemplateResponse("bots/edit.html", get_template_context(
            request, user=user, title=f"Редактирование: {edit_bot['name']}",
            edit_bot=edit_bot, stats=stats, message=msg
        ))

    @router.post("/{bot_id}/update", dependencies=[Depends(verify_csrf_token)])
    async def update_bot(
        request: Request,
        bot_id: int,
        name: str = Form(...),
        type: str = Form(...),
        user: str = Depends(get_current_user)
    ):
        from database.panel_db import get_panel_connection
        
        async with get_panel_connection() as db:
            await db.execute(
                "UPDATE bot_registry SET name = $2, type = $3 WHERE id = $1",
                bot_id, name, type
            )
        
        return RedirectResponse(
            url=f"/bots/{bot_id}/edit?msg=Изменения+сохранены",
            status_code=status.HTTP_303_SEE_OTHER
        )

    @router.post("/{bot_id}/admins", dependencies=[Depends(verify_csrf_token)])
    async def update_bot_admins(
        request: Request,
        bot_id: int,
        admin_ids: str = Form(""),
        user: str = Depends(get_current_user)
    ):
        from database.panel_db import get_panel_connection, update_bot
        
        parsed_ids = []
        if admin_ids.strip():
            for aid in admin_ids.replace(' ', '').split(','):
                try:
                    if aid.strip():
                        parsed_ids.append(int(aid.strip()))
                except ValueError:
                    pass
        
        await update_bot(bot_id, admin_ids=parsed_ids)
        
        return RedirectResponse(
            url=f"/bots/{bot_id}/edit?msg=Админы+обновлены",
            status_code=status.HTTP_303_SEE_OTHER
        )

    @router.post("/{bot_id}/modules", dependencies=[Depends(verify_csrf_token)])
    async def update_bot_modules_route(
        request: Request,
        bot_id: int,
        user: str = Depends(get_current_user)
    ):
        from database import update_bot_modules
        
        form = await request.form()
        modules = list(form.getlist('modules'))
        
        if 'registration' not in modules:
            modules.append('registration')
        
        await update_bot_modules(bot_id, modules)
        
        return RedirectResponse(
            url=f"/bots/{bot_id}/edit?msg=Модули+обновлены",
            status_code=status.HTTP_303_SEE_OTHER
        )

    @router.get("/{bot_id}/export")
    async def export_bot(request: Request, bot_id: int, user: Dict = Depends(require_superadmin)):
        bot = await get_bot_by_id(bot_id)
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        # Connect to bot's database
        if not bot_db_manager.get(bot_id):
            bot_db_manager.register(bot_id, bot['database_url'])
            await bot_db_manager.connect(bot_id)
        
        bot_db = bot_db_manager.get(bot_id)
        async with bot_db.get_connection() as db:
            users = await db.fetch("SELECT * FROM users")
            receipts = await db.fetch("SELECT * FROM receipts")
            promo_codes = await db.fetch("SELECT * FROM promo_codes")
            settings = await db.fetch("SELECT * FROM settings")
            messages = await db.fetch("SELECT * FROM messages")
            winners = await db.fetch("SELECT * FROM winners")
        
        def record_to_dict(record):
            d = dict(record)
            for k, v in d.items():
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
                elif isinstance(v, date):
                    d[k] = v.isoformat()
            return d
        
        export_data = {
            "exported_at": datetime.now().isoformat(),
            "bot": record_to_dict(bot),
            "users": [record_to_dict(r) for r in users],
            "receipts": [record_to_dict(r) for r in receipts],
            "promo_codes": [record_to_dict(r) for r in promo_codes],
            "settings": [record_to_dict(r) for r in settings],
            "messages": [record_to_dict(r) for r in messages],
            "winners": [record_to_dict(r) for r in winners],
            "stats": {
                "users_count": len(users),
                "receipts_count": len(receipts),
                "promo_codes_count": len(promo_codes),
                "winners_count": len(winners)
            }
        }
        
        filename = f"bot_{bot_id}_{bot['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        return JSONResponse(
            content=export_data,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    @router.post("/{bot_id}/delete", dependencies=[Depends(verify_csrf_token)])
    async def delete_bot_permanently(
        request: Request,
        bot_id: int,
        confirm: str = Form(...),
        user: Dict = Depends(require_superadmin)
    ):
        from database.panel_db import delete_bot_registry
        
        bot = await get_bot_by_id(bot_id)
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        if confirm != bot['name']:
            return RedirectResponse(
                url=f"/bots/{bot_id}/edit?msg=Неверное+подтверждение",
                status_code=status.HTTP_303_SEE_OTHER
            )
        
        # Delete data from bot's database
        if not bot_db_manager.get(bot_id):
            bot_db_manager.register(bot_id, bot['database_url'])
            await bot_db_manager.connect(bot_id)
        
        bot_db = bot_db_manager.get(bot_id)
        async with bot_db.get_connection() as db:
            await db.execute("DELETE FROM winners")
            await db.execute("DELETE FROM promo_codes")
            await db.execute("DELETE FROM receipts")
            await db.execute("DELETE FROM campaigns")
            await db.execute("DELETE FROM messages")
            await db.execute("DELETE FROM settings")
            await db.execute("DELETE FROM manual_tickets")
            await db.execute("DELETE FROM users")
        
        # Disconnect and remove bot database connection
        await bot_db_manager.disconnect(bot_id)
        
        # Delete from panel registry
        await delete_bot_registry(bot_id)
        
        if request.session.get("active_bot_id") == bot_id:
            request.session.pop("active_bot_id", None)
        
        logger.info(f"Bot {bot_id} ({bot['name']}) permanently deleted by {user['username']}")
        
        return RedirectResponse(url="/?msg=Бот+удалён", status_code=status.HTTP_303_SEE_OTHER)

    return router
