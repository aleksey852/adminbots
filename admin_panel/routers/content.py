"""
Content Editor Router — Редактирование content.py через панель.

Позволяет:
- Просматривать все тексты бота
- Редактировать тексты через веб-интерфейс
- Сохранять изменения в content.py
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Dict
import logging
import os
import json

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/content", tags=["content"])

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
    
    @router.get("/", response_class=HTMLResponse)
    async def content_editor_page(request: Request, user: Dict = Depends(get_current_user)):
        """Content editor - direct content.py editing"""
        bot = request.state.bot
        if not bot:
            return templates.TemplateResponse("content/editor.html", get_template_context(
                request, user=user, title="Контент", error="Нет активного бота"
            ))
        
        manifest_path = bot.get('manifest_path')
        if not manifest_path:
            return templates.TemplateResponse("content/editor.html", get_template_context(
                request, user=user, title="Контент",
                error="Этот бот не поддерживает редактирование контента (нет manifest_path)",
                bot=bot
            ))
        
        content_path = os.path.join(manifest_path, 'content.py')
        
        if not os.path.exists(content_path):
            raw_content = '''"""
Bot Content — Все тексты бота.

Создайте переменные UPPERCASE и они автоматически загрузятся.
"""

WELCOME = """
🎉 Добро пожаловать!
"""

MENU = """
📋 Главное меню
"""
'''
        else:
            with open(content_path, 'r', encoding='utf-8') as f:
                raw_content = f.read()
        
        return templates.TemplateResponse("content/editor.html", get_template_context(
            request, user=user, title="Редактор контента",
            raw_content=raw_content, content_path=content_path, bot=bot
        ))
    
    @router.post("/save", dependencies=[Depends(verify_csrf_token)])
    async def save_content(request: Request, user: Dict = Depends(get_current_user)):
        """Save content.py directly"""
        from utils.content_loader import reload_content
        
        bot = request.state.bot
        if not bot:
            raise HTTPException(400, "No active bot")
        
        manifest_path = bot.get('manifest_path')
        if not manifest_path:
            raise HTTPException(400, "Bot has no manifest path")
        
        content_path = os.path.join(manifest_path, 'content.py')
        
        form = await request.form()
        raw_content = form.get('raw_content', '')
        
        # Validate Python syntax
        try:
            compile(raw_content, content_path, 'exec')
        except SyntaxError as e:
            return RedirectResponse(f"/content?error=Синтаксическая+ошибка:+строка+{e.lineno}:+{e.msg}", status_code=303)
        
        # Write file
        try:
            with open(content_path, 'w', encoding='utf-8') as f:
                f.write(raw_content)
            
            # Reload content into bot's database
            reload_content(bot['id'])
            
            logger.info(f"Saved content for bot {bot['id']}")
            return RedirectResponse("/content?msg=Сохранено", status_code=303)
            
        except Exception as e:
            logger.error(f"Failed to save content: {e}")
            return RedirectResponse(f"/content?error={str(e)}", status_code=303)
    
    @router.get("/raw", response_class=HTMLResponse)
    async def raw_content_editor(request: Request, user: Dict = Depends(get_current_user)):
        """Raw content.py editor (advanced mode)"""
        bot = request.state.bot
        if not bot:
            raise HTTPException(400, "No active bot")
        
        manifest_path = bot.get('manifest_path')
        if not manifest_path:
            raise HTTPException(400, "Bot has no manifest path")
        
        content_path = os.path.join(manifest_path, 'content.py')
        
        if not os.path.exists(content_path):
            raw_content = "# Content file will be created"
        else:
            with open(content_path, 'r', encoding='utf-8') as f:
                raw_content = f.read()
        
        return templates.TemplateResponse("content/raw_editor.html", get_template_context(
            request, user=user, title="Редактор (raw)",
            raw_content=raw_content, content_path=content_path, bot=bot
        ))
    
    @router.post("/raw/save", dependencies=[Depends(verify_csrf_token)])
    async def save_raw_content(request: Request, user: Dict = Depends(get_current_user)):
        """Save raw content.py (advanced mode)"""
        from utils.content_loader import reload_content
        
        bot = request.state.bot
        if not bot:
            raise HTTPException(400, "No active bot")
        
        manifest_path = bot.get('manifest_path')
        if not manifest_path:
            raise HTTPException(400, "Bot has no manifest path")
        
        content_path = os.path.join(manifest_path, 'content.py')
        
        form = await request.form()
        raw_content = form.get('raw_content', '')
        
        # Validate Python syntax
        try:
            compile(raw_content, content_path, 'exec')
        except SyntaxError as e:
            return RedirectResponse(f"/content/raw?error=Синтаксическая+ошибка:+{e.msg}", status_code=303)
        
        # Write file
        try:
            with open(content_path, 'w', encoding='utf-8') as f:
                f.write(raw_content)
            
            reload_content(bot['id'])
            
            logger.info(f"Saved raw content for bot {bot['id']}")
            return RedirectResponse("/content/raw?msg=Сохранено", status_code=303)
            
        except Exception as e:
            logger.error(f"Failed to save raw content: {e}")
            return RedirectResponse(f"/content/raw?error={str(e)}", status_code=303)
    
    return router
