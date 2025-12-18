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
    get_all_pipeline_configs,
    set_pipeline_config,
    delete_pipeline_config
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
        chains = workflow_manager.chains.keys()
        
        return templates.TemplateResponse("modules/pipelines.html", get_template_context(
            request,
            user=user,
            bot=bot,
            chains=list(chains)
        ))


    async def get_pipeline_details(bot_id: int, chain_name: str, user: Dict = Depends(get_current_user)):
        """API to get steps for drag-n-drop editor"""
        default_steps = workflow_manager.get_steps(chain_name)
        custom_order_names = await get_all_pipeline_configs(bot_id)
        custom_order = custom_order_names.get(chain_name, [])
        enabled_modules = set(await get_bot_enabled_modules(bot_id))
        
        # Sort
        if custom_order:
            step_map = {s["name"]: s for s in default_steps}
            final_steps = []
            for name in custom_order:
                if name in step_map:
                    final_steps.append(step_map[name])
            for s in default_steps:
                if s["name"] not in custom_order:
                    final_steps.append(s)
        else:
            final_steps = default_steps
            
        # Sanitize steps for JSON response and inject is_enabled
        sanitized_steps = []
        for step in final_steps:
            safe_step = step.copy()
            if safe_step.get("state"):
                safe_step["state"] = str(safe_step["state"])
            
            # Check enabled status
            mod_name = safe_step.get("module_name")
            is_enabled = True
            if mod_name:
                is_enabled = mod_name in enabled_modules
            safe_step["is_enabled"] = is_enabled
            
            sanitized_steps.append(safe_step)

        return {
            "chain": chain_name,
            "steps": sanitized_steps
        }

    @router.post("/pipelines/{chain_name}/order")
    async def save_pipeline_order(bot_id: int, chain_name: str, order: list[str], user: Dict = Depends(get_current_user)):
        """Save new step order"""
        # Verify these steps exist in the chain definition
        valid_steps = {s["name"] for s in workflow_manager.get_steps(chain_name)}
        filtered_order = [name for name in order if name in valid_steps]
        
        await set_pipeline_config(bot_id, chain_name, filtered_order)
        return {"status": "success"}

    @router.post("/pipelines/{chain_name}/reset")
    async def reset_pipeline_order(bot_id: int, chain_name: str, user: Dict = Depends(get_current_user)):
        """Reset step order to default"""
        await delete_pipeline_config(bot_id, chain_name)
        return {"status": "success"}
    
    return router
