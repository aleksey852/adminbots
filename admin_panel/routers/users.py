"""Users management router: list, detail, search, block, message"""
from fastapi import APIRouter, Request, Depends, HTTPException, status, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Dict
import logging
import uuid
import time
import aiofiles

from database import (
    get_users_paginated, get_total_users_count, search_users,
    get_user_detail, get_user_receipts_detailed, add_receipt,
    block_user, update_user_fields
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])

# Will be set by setup_routes
templates = None
get_current_user = None
verify_csrf_token = None
get_template_context = None
UPLOADS_DIR = None


def setup_routes(
    app_templates: Jinja2Templates,
    auth_get_current_user,
    auth_verify_csrf_token,
    context_helper,
    uploads_dir: Path
):
    """Setup routes with dependencies"""
    global templates, get_current_user, verify_csrf_token, get_template_context, UPLOADS_DIR
    templates = app_templates
    get_current_user = auth_get_current_user
    verify_csrf_token = auth_verify_csrf_token
    get_template_context = context_helper
    UPLOADS_DIR = uploads_dir

    @router.get("", response_class=HTMLResponse)
    async def users_list(request: Request, user: str = Depends(get_current_user), page: int = 1, q: str = None):
        if not (bot := request.state.bot): return RedirectResponse("/")
        
        if q:
            users = await search_users(q)
            total = len(users)
            total_pages = 1
        else:
            users = await get_users_paginated(page=page, per_page=50)
            total = await get_total_users_count()
            total_pages = (total + 49) // 50
        
        return templates.TemplateResponse("users/list.html", get_template_context(
            request, user=user, users=users,
            page=page, total_pages=total_pages, total=total,
            search_query=q or "", title="Пользователи"
        ))

    @router.get("/{user_id}", response_class=HTMLResponse)
    async def user_detail_page(request: Request, user_id: int, user: str = Depends(get_current_user), msg: str = None):
        if not (bot := request.state.bot): return RedirectResponse("/")
        
        user_data = await get_user_detail(user_id)
        if not user_data or user_data['bot_id'] != bot['id']:
            raise HTTPException(404, "User not found")
        
        return templates.TemplateResponse("users/detail.html", get_template_context(
            request, user=user, user_data=user_data,
            receipts=await get_user_receipts_detailed(user_id, limit=50), 
            title=f"Пользователь #{user_id}", message=msg
        ))

    @router.post("/{user_id}/message", dependencies=[Depends(verify_csrf_token)])
    async def send_user_message(
        request: Request, user_id: int, text: str = Form(None),
        photo: UploadFile = File(None), user: str = Depends(get_current_user)
    ):
        if not (bot := request.state.bot): return RedirectResponse("/")
        
        user_data = await get_user_detail(user_id)
        if not user_data or user_data['bot_id'] != bot['id']:
            raise HTTPException(404, "User not found")

        content = {}
        if photo and photo.filename:
            filename = f"{uuid.uuid4()}{Path(photo.filename).suffix or '.jpg'}"
            filepath = UPLOADS_DIR / filename
            async with aiofiles.open(filepath, 'wb') as f:
                while chunk := await photo.read(1024 * 1024):
                    await f.write(chunk)
            content.update({"photo_path": str(filepath), "caption": text})
        elif text:
            content["text"] = text
        else:
            return RedirectResponse(f"/users/{user_id}?msg=error_empty", 303)
        
        from aiogram import Bot as AiogramBot
        from aiogram.types import FSInputFile
        
        bot_instance = AiogramBot(token=bot['token'])
        try:
            if "photo_path" in content:
                await bot_instance.send_photo(user_data['telegram_id'], FSInputFile(content["photo_path"]), caption=content.get("caption"))
            else:
                await bot_instance.send_message(user_data['telegram_id'], content.get("text", ""))
            return RedirectResponse(f"/users/{user_id}?msg=sent", 303)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return RedirectResponse(f"/users/{user_id}?msg=error", 303)
        finally:
            await bot_instance.session.close()

    @router.post("/{user_id}/add-receipt", dependencies=[Depends(verify_csrf_token)])
    async def add_user_receipt(request: Request, user_id: int, user: str = Depends(get_current_user)):
        if not (bot := request.state.bot): return RedirectResponse("/")
        if not (user_data := await get_user_detail(user_id)) or user_data['bot_id'] != bot['id']:
            raise HTTPException(404, "User not found")
        
        ts = int(time.time())
        await add_receipt(
            user_id=user_id, status="valid",
            data={"manual": True, "admin": user, "source": "web_panel"},
            fiscal_drive_number="MANUAL",
            fiscal_document_number=f"M_{ts}_{uuid.uuid4().hex[:4]}",
            fiscal_sign=f"M_{user_id}_{ts}",
            total_sum=0, raw_qr="manual_web",
            product_name="Ручное добавление (веб)"
        )
        return RedirectResponse(f"/users/{user_id}?msg=receipt_added", 303)

    @router.post("/{user_id}/block", dependencies=[Depends(verify_csrf_token)])
    async def toggle_user_block(request: Request, user_id: int, user: str = Depends(get_current_user)):
        user_data = await get_user_detail(user_id)
        if not user_data: raise HTTPException(404, "User not found")
        
        new_status = not user_data.get('is_blocked', False)
        await block_user(user_id, new_status)
        return RedirectResponse(f"/users/{user_id}?msg={'blocked' if new_status else 'unblocked'}", 303)

    @router.post("/{user_id}/add-tickets", dependencies=[Depends(verify_csrf_token)])
    async def add_user_tickets(
        request: Request, user_id: int, tickets: int = Form(...),
        reason: str = Form(None), user: Dict = Depends(get_current_user)
    ):
        if not (bot := request.state.bot): return RedirectResponse("/")
        user_data = await get_user_detail(user_id)
        if not user_data or user_data['bot_id'] != bot['id']:
            raise HTTPException(404, "User not found")
        
        from database.bot_methods import add_manual_tickets, bot_db_context
        created_by = user.get('username', 'admin') if isinstance(user, dict) else str(user)
        async with bot_db_context(bot['id']):
            await add_manual_tickets(user_id, max(1, min(tickets, 10000)), reason, created_by)
        return RedirectResponse(f"/users/{user_id}?msg=tickets_added", 303)

    @router.post("/{user_id}/update", dependencies=[Depends(verify_csrf_token)])
    async def update_user_profile(
        request: Request, user_id: int, full_name: str = Form(None),
        phone: str = Form(None), username: str = Form(None), user: str = Depends(get_current_user)
    ):
        if not (bot := request.state.bot): return RedirectResponse("/")
        user_data = await get_user_detail(user_id)
        if not user_data or user_data['bot_id'] != bot['id']:
            raise HTTPException(404, "User not found")

        await update_user_fields(
            user_id,
            full_name=full_name.strip() if full_name else user_data.get("full_name"),
            phone=phone.strip() if phone else user_data.get("phone"),
            username=username.strip().lstrip("@") if username else user_data.get("username"),
        )
        return RedirectResponse(f"/users/{user_id}?msg=updated", 303)

    return router
