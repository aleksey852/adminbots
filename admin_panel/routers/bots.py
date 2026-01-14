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
        """Show available bot templates from bots/ folder"""
        from utils.bot_discovery import get_templates_with_status
        
        templates_list = await get_templates_with_status()
        
        return templates.TemplateResponse("bots/new.html", get_template_context(
            request, user=user, title="Добавить бота",
            bot_templates=templates_list
        ))

    @router.post("/create", dependencies=[Depends(verify_csrf_token)])
    async def create_bot(
        request: Request, 
        template_path: str = Form(...),
        bot_name: str = Form(...),
        token: str = Form(...), 
        admin_ids: str = Form(""),
        require_subscription: str = Form(None),
        channel_id: str = Form(""),
        channel_url: str = Form(""),
        user: Dict = Depends(require_superadmin)
    ):
        """Activate a bot template with the given token"""
        from utils.bot_discovery import activate_bot_template, get_templates_with_status
        
        if not token or ":" not in token:
            templates_list = await get_templates_with_status()
            return templates.TemplateResponse("bots/new.html", get_template_context(
                request, user=user, title="Добавить бота", 
                error="Неверный формат токена",
                bot_templates=templates_list
            ))
        
        try:
            # Parse admin IDs
            admin_id_list = [int(x.strip()) for x in admin_ids.split(',') if x.strip().isdigit()]
            
            # Parse subscription settings - use registration module's key names
            subscription_settings = None
            if require_subscription and channel_id.strip():
                subscription_settings = {
                    "subscription_required": "true",
                    "subscription_channel_id": channel_id.strip(),
                    "subscription_channel_url": channel_url.strip() if channel_url else ""
                }
            
            # Activate template
            result = await activate_bot_template(
                template_path=template_path,
                token=token,
                admin_ids=admin_id_list,
                custom_name=bot_name,
                initial_settings=subscription_settings
            )
            
            request.session["active_bot_id"] = result['bot_id']
            return RedirectResponse(f"/?msg=Бот+{result['name']}+активирован", 303)
            
        except ValueError as e:
            templates_list = await get_templates_with_status()
            return templates.TemplateResponse("bots/new.html", get_template_context(
                request, user=user, title="Добавить бота",
                error=str(e),
                bot_templates=templates_list
            ))
        except Exception as e:
            logger.error(f"Bot activation failed: {e}")
            templates_list = await get_templates_with_status()
            return templates.TemplateResponse("bots/new.html", get_template_context(
                request, user=user, title="Добавить бота",
                error=f"Ошибка активации: {e}",
                bot_templates=templates_list
            ))

    @router.get("/{bot_id}/edit", response_class=HTMLResponse)
    async def edit_bot_page(request: Request, bot_id: int, user: Dict = Depends(require_superadmin), msg: str = None):
        from database.bot_methods import get_stats, bot_db_context
        from utils.config_manager import config_manager
        from core.module_loader import module_loader
        
        bot = await get_bot_by_id(bot_id)
        if not bot: raise HTTPException(404, "Bot not found")
        
        if not bot_db_manager.get(bot_id):
            bot_db_manager.register(bot_id, bot['database_url'])
            await bot_db_manager.connect(bot_id)
        
        if not config_manager._initialized: await config_manager.load()
        await config_manager.load_for_bot(bot_id)
        
        # --- Modules & Settings Logic ---
        enabled_modules = set(bot.get('enabled_modules') or [])
        modules_data = []
        
        # Sort: core/registration first, then others
        sorted_modules = sorted(
            module_loader.modules.values(), 
            key=lambda x: 0 if x.name in ('core', 'registration') else 1
        )

        async with bot_db_context(bot_id):
            # Fetch stats
            stats = await get_stats()
            
            # Prepare module data with settings
            for mod in sorted_modules:
                settings = []
                if hasattr(mod, 'settings_schema'):
                    for key, schema in mod.settings_schema.items():
                        current_val = config_manager.get_setting(key, schema.get('default'), bot_id)
                        settings.append({
                            'key': key,
                            'value': current_val,
                            **schema
                        })
                
                modules_data.append({
                    'name': mod.name,
                    'description': mod.description,
                    'enabled': mod.name in enabled_modules,
                    'is_required': mod.name in ('core', 'registration'),
                    'settings': settings
                })

        promo_start = config_manager.get_setting('promo_start_date', config.PROMO_START_DATE, bot_id)
        promo_end = config_manager.get_setting('promo_end_date', config.PROMO_END_DATE, bot_id)

        return templates.TemplateResponse("bots/edit.html", get_template_context(
            request, user=user, title=f"Бот: {bot['name']}", edit_bot=bot, stats=stats, message=msg,
            modules=modules_data,
            promo_dates={"start": promo_start, "end": promo_end}
        ))

    @router.post("/{bot_id}/update", dependencies=[Depends(verify_csrf_token)])
    async def update_bot_info(
        request: Request, bot_id: int, name: str = Form(...), type: str = Form(None),
        user: Dict = Depends(require_superadmin)
    ):
        """Update bot basic info (name, type)"""
        from database.panel_db import update_bot
        
        bot = await get_bot_by_id(bot_id)
        if not bot:
            raise HTTPException(404, "Bot not found")
        
        kwargs = {"name": name.strip()}
        if type:
            kwargs["type"] = type
            
        await update_bot(bot_id, **kwargs)
        return RedirectResponse(f"/bots/{bot_id}/edit?msg=Bot+info+updated", 303)

    @router.post("/{bot_id}/admins", dependencies=[Depends(verify_csrf_token)])
    async def update_bot_admins(
        request: Request, bot_id: int, admin_ids: str = Form(""),
        user: Dict = Depends(require_superadmin)
    ):
        """Update bot admin IDs"""
        from database.panel_db import update_bot
        
        bot = await get_bot_by_id(bot_id)
        if not bot:
            raise HTTPException(404, "Bot not found")
        
        # Parse admin IDs
        parsed_ids = [int(x.strip()) for x in admin_ids.split(',') if x.strip().isdigit()]
        await update_bot(bot_id, admin_ids=parsed_ids)
        return RedirectResponse(f"/bots/{bot_id}/edit?msg=Admins+updated", 303)

    @router.post("/{bot_id}/modules", dependencies=[Depends(verify_csrf_token)])
    async def update_bot_modules(request: Request, bot_id: int):
        from database.panel_db import update_bot
        from utils.config_manager import config_manager
        from core.module_loader import module_loader
        
        form = await request.form()
        
        # 1. Update Enabled Modules
        modules = list(form.getlist('modules'))
        if 'registration' not in modules: modules.append('registration')
        if 'core' not in modules: modules.append('core')
        await update_bot(bot_id, enabled_modules=modules)
        
        # 2. Update Settings
        # Iterate over all known schemas and check form for values
        for mod in module_loader.modules.values():
            if hasattr(mod, 'settings_schema'):
                for key in mod.settings_schema:
                    if key in form:
                        value = form[key]
                        await config_manager.set_setting(key, value, bot_id)
        
        return RedirectResponse(f"/bots/{bot_id}/edit?msg=Modules+updated", 303)

    @router.post("/{bot_id}/campaign", dependencies=[Depends(verify_csrf_token)])
    async def update_campaign_dates(
        request: Request, bot_id: int, 
        start_date: str = Form(...), 
        end_date: str = Form(...),
        user: Dict = Depends(require_superadmin)
    ):
        """Update campaign start/end dates"""
        from utils.config_manager import config_manager
        from database.panel_db import get_bot_by_id
        from database.bot_db import bot_db_manager
        
        # Simple validation
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
             return RedirectResponse(f"/bots/{bot_id}/edit?error=Invalid+date+format", 303)
             
        # Ensure DB connected
        bot = await get_bot_by_id(bot_id)
        if not bot: raise HTTPException(404, "Bot not found")
        
        if not bot_db_manager.get(bot_id):
            bot_db_manager.register(bot_id, bot['database_url'])
            await bot_db_manager.connect(bot_id)

        await config_manager.set_setting("promo_start_date", start_date, bot_id)
        await config_manager.set_setting("promo_end_date", end_date, bot_id)
        
        from database.panel_db import notify_reload_config
        await notify_reload_config(bot_id)
        
        return RedirectResponse(f"/bots/{bot_id}/edit?msg=Dates+updated", 303)

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

    @router.post("/{bot_id}/archive", dependencies=[Depends(verify_csrf_token)])
    async def archive_bot_endpoint(request: Request, bot_id: int, user: Dict = Depends(require_superadmin)):
        from database.panel_db import archive_bot
        await archive_bot(bot_id, "panel")
        if request.session.get("active_bot_id") == bot_id:
            request.session.pop("active_bot_id", None)
        return RedirectResponse("/?msg=Archived", 303)

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

    @router.get("/{bot_id}/export/full")
    async def export_bot_full(request: Request, bot_id: int, user: Dict = Depends(require_superadmin)):
        """Export full bot archive as ZIP"""
        import io
        import zipfile
        from fastapi.responses import StreamingResponse
        from database.panel_db import get_all_module_settings
        from database.bot_db import bot_db_manager
        from database.bot_methods import bot_db_context
        from utils.config_manager import config_manager
        
        bot = await get_bot_by_id(bot_id)
        if not bot:
            raise HTTPException(404, "Bot not found")
        
        # Ensure DB connected
        if not bot_db_manager.get(bot_id):
            bot_db_manager.register(bot_id, bot['database_url'])
            await bot_db_manager.connect(bot_id)
        
        # Create manifest
        manifest = {
            "name": bot['name'],
            "type": bot['type'],
            "version": "1.0.0",
            "exported_at": datetime.now().isoformat(),
            "enabled_modules": list(bot.get('enabled_modules') or []),
            "admin_ids": list(bot.get('admin_ids') or [])
        }
        
        # Get module settings
        module_settings = await get_all_module_settings(bot_id)
        
        # Get texts/config
        if not config_manager._initialized:
            await config_manager.load()
        texts = config_manager.get_bot_config(bot_id)
        
        config_data = {
            "module_settings": module_settings,
            "texts": texts
        }
        
        # Get database data
        data = {"users": [], "receipts": [], "codes": [], "winners": []}
        
        async with bot_db_context(bot_id):
            db = bot_db_manager.get(bot_id)
            async with db.get_connection() as conn:
                # Users
                rows = await conn.fetch("SELECT * FROM users LIMIT 50000")
                for r in rows:
                    user_data = dict(r)
                    for k, v in user_data.items():
                        if isinstance(v, (datetime, date)):
                            user_data[k] = v.isoformat()
                    data["users"].append(user_data)
                
                # Receipts
                rows = await conn.fetch("SELECT * FROM receipts LIMIT 50000")
                for r in rows:
                    receipt = dict(r)
                    for k, v in receipt.items():
                        if isinstance(v, (datetime, date)):
                            receipt[k] = v.isoformat()
                    data["receipts"].append(receipt)
                
                # Promo codes
                rows = await conn.fetch("SELECT * FROM promo_codes LIMIT 50000")
                for r in rows:
                    code = dict(r)
                    for k, v in code.items():
                        if isinstance(v, (datetime, date)):
                            code[k] = v.isoformat()
                    data["codes"].append(code)
                
                # Winners
                rows = await conn.fetch("SELECT * FROM winners LIMIT 50000")
                for r in rows:
                    winner = dict(r)
                    for k, v in winner.items():
                        if isinstance(v, (datetime, date)):
                            winner[k] = v.isoformat()
                    data["winners"].append(winner)
        
        # Create ZIP in memory
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr("config.json", json.dumps(config_data, ensure_ascii=False, indent=2))
            zf.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=2))
        
        buffer.seek(0)
        filename = f"bot_export_{bot['name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.zip"
        
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    @router.get("/import", response_class=HTMLResponse)
    async def import_bot_page(request: Request, user: Dict = Depends(require_superadmin)):
        return templates.TemplateResponse("bots/import.html", get_template_context(request, user=user, title="\u0418\u043c\u043f\u043e\u0440\u0442 \u0431\u043e\u0442\u0430"))

    @router.post("/import", dependencies=[Depends(verify_csrf_token)])
    async def import_bot(request: Request, user: Dict = Depends(require_superadmin)):
        """Import bot from ZIP archive"""
        import io
        import zipfile
        from database.panel_db import register_bot, create_bot_database, set_module_settings, get_panel_connection
        
        form = await request.form()
        file = form.get("archive")
        token = form.get("token", "")
        
        if not file or not token:
            return templates.TemplateResponse("bots/import.html", get_template_context(
                request, user=user, title="\u0418\u043c\u043f\u043e\u0440\u0442 \u0431\u043e\u0442\u0430", error="\u0422\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f \u0430\u0440\u0445\u0438\u0432 \u0438 \u0442\u043e\u043a\u0435\u043d"
            ))
        
        try:
            content = await file.read()
            zf = zipfile.ZipFile(io.BytesIO(content))
            
            manifest = json.loads(zf.read("manifest.json").decode('utf-8'))
            config_data = json.loads(zf.read("config.json").decode('utf-8'))
            data = json.loads(zf.read("data.json").decode('utf-8'))
            
            # Check token not exists
            if await get_bot_by_token(token):
                return templates.TemplateResponse("bots/import.html", get_template_context(
                    request, user=user, title="\u0418\u043c\u043f\u043e\u0440\u0442 \u0431\u043e\u0442\u0430", error="\u0411\u043e\u0442 \u0441 \u0442\u0430\u043a\u0438\u043c \u0442\u043e\u043a\u0435\u043d\u043e\u043c \u0443\u0436\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442"
                ))
            
            import re
            name = manifest.get("name", "Imported Bot")
            bot_type = manifest.get("type", "receipt")
            admin_ids = manifest.get("admin_ids", [])
            
            db_url = await create_bot_database(
                f"bot_{re.sub(r'[^a-z0-9_]', '', name.lower())[:20]}_{uuid.uuid4().hex[:6]}",
                config.DATABASE_URL
            )
            
            bid = await register_bot(token=token, name=name, bot_type=bot_type, database_url=db_url, admin_ids=admin_ids)
            bot_db_manager.register(bid, db_url)
            await bot_db_manager.connect(bid)
            
            # Restore module settings
            for mod_name, settings in config_data.get("module_settings", {}).items():
                await set_module_settings(bid, mod_name, settings)
            
            # TODO: Restore texts and data (users, receipts, codes) if needed
            # This is a basic implementation - full data restore is complex
            
            async with get_panel_connection() as db:
                await db.execute("NOTIFY new_bot")
            
            request.session["active_bot_id"] = bid
            return RedirectResponse(f"/bots/{bid}/edit?msg=Bot+imported", 303)
            
        except Exception as e:
            logger.error(f"Import failed: {e}")
            return templates.TemplateResponse("bots/import.html", get_template_context(
                request, user=user, title="\u0418\u043c\u043f\u043e\u0440\u0442 \u0431\u043e\u0442\u0430", error=str(e)
            ))

    return router
