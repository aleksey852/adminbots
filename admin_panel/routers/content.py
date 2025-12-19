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
        """Content editor main page"""
        from database.panel_db import get_bot_by_id
        from utils.content_loader import list_content_keys, get_bot_content
        
        bot = request.state.bot
        if not bot:
            return templates.TemplateResponse("content/editor.html", get_template_context(
                request, user=user, title="Контент", error="Нет активного бота"
            ))
        
        bot_id = bot['id']
        manifest_path = bot.get('manifest_path')
        
        # Check if bot has manifest path
        if not manifest_path:
            return templates.TemplateResponse("content/editor.html", get_template_context(
                request, user=user, title="Контент",
                error="Этот бот не поддерживает редактирование контента (нет manifest_path)",
                bot=bot
            ))
        
        # Check if content.py exists
        content_path = os.path.join(manifest_path, 'content.py')
        if not os.path.exists(content_path):
            return templates.TemplateResponse("content/editor.html", get_template_context(
                request, user=user, title="Контент",
                error=f"Файл content.py не найден: {content_path}",
                bot=bot
            ))
        
        # Load content
        try:
            content_data = list_content_keys(bot_id)
            
            # Group content by category
            sections = {
                "main": {"title": "Основные тексты", "items": {}},
                "buttons": {"title": "Кнопки", "items": {}},
                "promo": {"title": "Промокоды", "items": {}},
                "raffle": {"title": "Розыгрыши", "items": {}},
                "subscription": {"title": "Подписка", "items": {}},
                "admin": {"title": "Админ уведомления", "items": {}},
                "system": {"title": "Системные", "items": {}},
                "faq": {"title": "FAQ", "items": {}},
                "other": {"title": "Прочее", "items": {}},
            }
            
            for key, value in content_data.items():
                if key.startswith('BTN_'):
                    sections["buttons"]["items"][key] = value
                elif key.startswith('PROMO_'):
                    sections["promo"]["items"][key] = value
                elif key.startswith('RAFFLE_'):
                    sections["raffle"]["items"][key] = value
                elif key.startswith('SUBSCRIPTION_'):
                    sections["subscription"]["items"][key] = value
                elif key.startswith('ADMIN_'):
                    sections["admin"]["items"][key] = value
                elif key.startswith('ERROR_') or key == 'MAINTENANCE':
                    sections["system"]["items"][key] = value
                elif key.startswith('FAQ'):
                    sections["faq"]["items"][key] = value
                elif key in ('WELCOME', 'MENU', 'PROFILE'):
                    sections["main"]["items"][key] = value
                else:
                    sections["other"]["items"][key] = value
            
            # Remove empty sections
            sections = {k: v for k, v in sections.items() if v["items"]}
            
            return templates.TemplateResponse("content/editor.html", get_template_context(
                request, user=user, title="Редактор контента",
                sections=sections, content_path=content_path, bot=bot
            ))
            
        except Exception as e:
            logger.error(f"Failed to load content for bot {bot_id}: {e}")
            return templates.TemplateResponse("content/editor.html", get_template_context(
                request, user=user, title="Контент", error=str(e), bot=bot
            ))
    
    @router.post("/save", dependencies=[Depends(verify_csrf_token)])
    async def save_content(request: Request, user: Dict = Depends(get_current_user)):
        """Save updated content to content.py"""
        from utils.content_loader import reload_content
        
        bot = request.state.bot
        if not bot:
            raise HTTPException(400, "No active bot")
        
        manifest_path = bot.get('manifest_path')
        if not manifest_path:
            raise HTTPException(400, "Bot has no manifest path")
        
        content_path = os.path.join(manifest_path, 'content.py')
        
        # Get form data
        form = await request.form()
        content_data = {}
        
        for key in form.keys():
            if key.startswith('content_'):
                real_key = key.replace('content_', '')
                content_data[real_key] = form[key]
        
        # Also handle FAQ as JSON if present
        faq_json = form.get('faq_items')
        if faq_json:
            try:
                content_data['FAQ_ITEMS'] = json.loads(faq_json)
            except json.JSONDecodeError:
                pass
        
        # Generate Python file
        lines = [
            '"""',
            'Bot Content — Тексты бота.',
            '',
            'Файл сгенерирован через Admin Panel.',
            '"""',
            ''
        ]
        
        for key, value in content_data.items():
            if isinstance(value, str):
                if '\n' in value or len(value) > 80:
                    # Multiline string
                    escaped = value.replace('"""', '\\"\\"\\"')
                    lines.append(f'{key} = """')
                    lines.append(escaped)
                    lines.append('"""')
                else:
                    # Single line string
                    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
                    lines.append(f'{key} = "{escaped}"')
            elif isinstance(value, dict):
                lines.append(f'{key} = {json.dumps(value, ensure_ascii=False, indent=4)}')
            lines.append('')
        
        # Write file
        try:
            with open(content_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            # Reload content
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
