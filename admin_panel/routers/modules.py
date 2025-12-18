from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Dict

from database.panel_db import (
    get_bot_by_id, 
    update_bot_modules, 
    get_bot_enabled_modules,
    get_module_settings,
    set_module_settings
)
from modules.base import module_loader

router = APIRouter(prefix="/bots/{bot_id}", tags=["modules"])

def setup_routes(
    templates: Jinja2Templates,
    get_current_user,
    verify_csrf_token,
    get_template_context
):
    
    @router.get("/modules", response_class=HTMLResponse)
    async def list_modules_page(request: Request, bot_id: int, user: Dict = Depends(get_current_user)):
        bot = await get_bot_by_id(bot_id)
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        enabled_modules = set(await get_bot_enabled_modules(bot_id))
        all_modules = module_loader.get_all_modules()
        
        modules_data = []
        for mod in all_modules:
            settings = await mod.get_settings(bot_id)
            modules_data.append({
                "name": mod.name,
                "description": mod.description,
                "version": mod.version,
                "is_enabled": mod.name in enabled_modules,
                "settings": settings,
                "schema": mod.settings_schema,
                "is_core": mod.name == "core"
            })
        
        return templates.TemplateResponse("modules/list.html", get_template_context(
            request, 
            user=user,
            bot=bot,
            modules=modules_data
        ))

    @router.post("/modules/{module_name}/toggle")
    async def toggle_module(bot_id: int, module_name: str, enable: bool, user: Dict = Depends(get_current_user)):
        """Enable or disable a module"""
        # Verify module exists
        mod = module_loader.get_module(module_name)
        if not mod:
            raise HTTPException(404, "Module not found")
            
        enabled_modules = set(await get_bot_enabled_modules(bot_id))
        
        if enable:
            enabled_modules.add(module_name)
            await mod.on_enable(bot_id)
        else:
            if module_name == "core":
                 raise HTTPException(400, "Cannot disable core module")
            enabled_modules.discard(module_name)
            await mod.on_disable(bot_id)
        
        await update_bot_modules(bot_id, list(enabled_modules))
        
        return {"status": "success", "enabled": enable}

    @router.post("/modules/{module_name}/settings")
    async def save_module_settings_endpoint(bot_id: int, module_name: str, settings: dict, user: Dict = Depends(get_current_user)):
        mod = module_loader.get_module(module_name)
        if not mod:
            raise HTTPException(404, "Module not found")
            
        await mod.save_settings(bot_id, settings)
        return {"status": "success"}
    
    return router
