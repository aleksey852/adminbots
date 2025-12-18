from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Dict, List, Optional
import logging

from database.panel_db import get_panel_connection
from utils.config_manager import config_manager

# Import modules to get defaults
from modules.core import core_module
from modules.registration import registration_module
from modules.receipts import receipts_module
from modules.promo import promo_module
from modules.admin import admin_module

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/texts", tags=["texts"])

ALL_MODULES = [core_module, registration_module, receipts_module, promo_module, admin_module]

CATEGORIES = {
    "welcome": ("🏠 Приветствие и Меню", 1),
    "menu": ("🏠 Приветствие и Меню", 1),
    "help": ("🏠 Приветствие и Меню", 1),
    "go_to_menu": ("🏠 Приветствие и Меню", 1),
    
    "reg": ("👤 Регистрация", 2),
    
    "status": ("📊 Профиль и Статус", 3),
    "profile": ("📊 Профиль и Статус", 3),
    
    "receipt": ("🧾 Чеки", 4),
    "promo": ("🎟 Промокоды", 5),
    
    "faq": ("❓ FAQ", 6),
    "support": ("📞 Поддержка", 7),
    
    "sub": ("📢 Подписка", 8),
    
    "win": ("🏆 Розыгрыши", 9),
    "lose": ("🏆 Розыгрыши", 9),
    
    "admin": ("🔧 Админка", 10),
    
    "cancel": ("❌ Общее", 11),
    "not_registered": ("❌ Общее", 11),
    "error": ("❌ Общее", 11),
}

DEFAULT_CATEGORY = ("📝 Разное", 99)

def get_category_info(key: str):
    for prefix, info in CATEGORIES.items():
        if key.startswith(prefix):
            return info
            
    if "admin" in key: return CATEGORIES["admin"]
    
    return DEFAULT_CATEGORY

# Global variables for dependency injection
templates: Optional[Jinja2Templates] = None
get_current_user = None
verify_csrf_token = None
get_template_context = None

def setup_routes(
    app_templates: Jinja2Templates,
    auth_get_current_user,
    auth_verify_csrf_token,
    context_helper
):
    global templates, get_current_user, verify_csrf_token, get_template_context
    templates = app_templates
    get_current_user = auth_get_current_user
    verify_csrf_token = auth_verify_csrf_token
    get_template_context = context_helper

    @router.get("", response_class=HTMLResponse)
    async def list_texts(request: Request, user: Dict = Depends(get_current_user)):
        bot = request.state.bot
        if not bot:
            return templates.TemplateResponse("dashboard.html", {"request": request, "error": "No bot selected"})
            
        bot_id = bot['id']
        
        # 1. Collect all defaults
        all_defaults = {}
        for mod in ALL_MODULES:
            all_defaults.update(mod.default_messages)
            
        # 2. Get current DB values
        try:
            # config_manager.get_all_messages expects to be called within specific context or just uses current request state if properly set up.
            # In app.py middleware, we set request.state.bot_db and call bot_methods.set_current_bot_db(bot_db).
            # So config_manager methods should work fine as they use bot_methods.get_current_bot_db().
            
            rows = await config_manager.get_all_messages(bot_id)
            db_messages = {row['key']: row['text'] for row in rows}
        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            db_messages = {}

        # 3. Merge and Group
        grouped = {}
        
        all_keys = set(all_defaults.keys()) | set(db_messages.keys())
        
        for key in sorted(all_keys):
            default = all_defaults.get(key, "")
            value = db_messages.get(key, default)
            cat_name, cat_order = get_category_info(key)
            
            if cat_name not in grouped:
                grouped[cat_name] = {'order': cat_order, 'items': []}
                
            grouped[cat_name]['items'].append({
                'key': key,
                'default': default,
                'value': value,
                'is_modified': key in db_messages and db_messages[key] != default
            })
            
        # Sort groups by order
        sorted_groups = sorted(grouped.items(), key=lambda x: x[1]['order'])
        
        # Prepare list for template
        final_groups = []
        for name, data in sorted_groups:
            final_groups.append({
                'name': name,
                'messages': data['items']
            })

        return templates.TemplateResponse("settings/texts.html", get_template_context(
            request, 
            user=user, 
            title="Тексты бота",
            groups=final_groups
        ))

    @router.post("/update", dependencies=[Depends(verify_csrf_token)])
    async def update_text(request: Request, key: str = Form(...), text: str = Form(...), user: Dict = Depends(get_current_user)):
        bot = request.state.bot
        if not bot:
            return JSONResponse({'error': 'No bot'}, status=400)
            
        bot_id = bot['id']
        
        try:
            # Update DB
            await config_manager.set_message(key, text, bot_id)
            
            # Send notification to bot process
            async with get_panel_connection() as db:
                await db.conn.execute(f"NOTIFY reload_config, '{bot_id}'")
                
            return JSONResponse({'status': 'ok', 'key': key})
        except Exception as e:
            logger.error(f"Failed to update text: {e}")
            return JSONResponse({'error': str(e)}, status=500)

    @router.post("/reset", dependencies=[Depends(verify_csrf_token)])
    async def reset_text(request: Request, key: str = Form(...), user: Dict = Depends(get_current_user)):
        bot = request.state.bot
        if not bot:
            return JSONResponse({'error': 'No bot'}, status=400)
            
        bot_id = bot['id']
        
        try:
            # Delete from DB
            from database.bot_methods import get_current_bot_db
            db = get_current_bot_db()
            async with db.get_connection() as conn:
                await conn.execute("DELETE FROM messages WHERE key = $1", key)
                
            # Notify
            async with get_panel_connection() as db:
                await db.conn.execute(f"NOTIFY reload_config, '{bot_id}'")
                
            # Dictionary reload for consistency in Admin Panel? 
            # config_manager inside admin panel assumes per-bot context but doesn't cache persistently across checks in a way that breaks this.
            # Wait, utils/config_manager.py uses global _messages dict.
            # If Admin Panel is a single process, we should update cache here too.
            # set_message updates cache.
            # But DELETE we just did manually. So we should clear it from cache manually.
            if bot_id in config_manager._messages and key in config_manager._messages[bot_id]:
                del config_manager._messages[bot_id][key]
                
            return JSONResponse({'status': 'ok', 'key': key})
        except Exception as e:
            logger.error(f"Failed to reset text: {e}")
            return JSONResponse({'error': str(e)}, status=500)
