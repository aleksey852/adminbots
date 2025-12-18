from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Dict

from database.panel_db import (
    get_bot_by_id, 
    update_bot_modules, 
    get_bot_enabled_modules,
    get_module_settings,
    set_module_settings,
    get_all_pipeline_configs,
    set_pipeline_config
)
from modules.base import module_loader
from modules.workflow import workflow_manager

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


    # === Pipeline Routes ===

    @router.get("/pipelines", response_class=HTMLResponse)
    async def list_pipelines_page(request: Request, bot_id: int, user: Dict = Depends(get_current_user)):
        bot = await get_bot_by_id(bot_id)
        if not bot:
            raise HTTPException(404, "Bot not found")
            
        # Get all chains
        chains = workflow_manager.default_chains.keys()
        
        return templates.TemplateResponse("modules/pipelines.html", get_template_context(
            request,
            user=user,
            bot=bot,
            chains=list(chains)
        ))


    @router.get("/pipelines/{chain_name}")
    async def get_pipeline_details(bot_id: int, chain_name: str, user: Dict = Depends(get_current_user)):
        """API to get steps for drag-n-drop editor"""
        # 1. Get all globally available steps from registry
        all_steps = workflow_manager.get_all_steps()
        
        # 2. Get current pipeline configuration (list of IDs)
        # If DB is empty, use default chain
        custom_ids = await get_all_pipeline_configs(bot_id)
        current_ids = custom_ids.get(chain_name)
        
        if current_ids is None:
             # Load default chain
             current_ids = workflow_manager.default_chains.get(chain_name, [])
        
        # 3. Separate into Active and Available
        active_steps = []
        active_ids_set = set()
        
        # Resolve active steps in order
        for step_id in current_ids:
            step = workflow_manager.step_registry.get(step_id)
            if step:
                active_steps.append(step)
                active_ids_set.add(step_id)
        
        # Resolve available (unused) steps
        available_steps = []
        for step in all_steps:
            if step['id'] not in active_ids_set:
                available_steps.append(step)

        # Helper to sanitize (convert non-serializable objects like State)
        def sanitize(steps):
             out = []
             for s in steps:
                 c = s.copy()
                 if c.get("state"):
                     c["state"] = str(c["state"])
                 out.append(c)
             return out

        return {
            "chain": chain_name,
            "active_steps": sanitize(active_steps),
            "available_steps": sanitize(available_steps)
        }

    @router.post("/pipelines/{chain_name}/order")
    async def save_pipeline_order(bot_id: int, chain_name: str, order: list[str], user: Dict = Depends(get_current_user)):
        """Save new step order (list of step_ids)"""
        # Verify these steps exist in the registry
        valid_ids = set(workflow_manager.step_registry.keys())
        
        filtered_order = [sid for sid in order if sid in valid_ids]
        
        await set_pipeline_config(bot_id, chain_name, filtered_order)
        return {"status": "success"}
    
    return router
