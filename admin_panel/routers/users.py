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
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")
        
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
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")
        
        user_data = await get_user_detail(user_id)
        if not user_data or user_data['bot_id'] != bot['id']:
            raise HTTPException(status_code=404, detail="User not found")
        
        receipts = await get_user_receipts_detailed(user_id, limit=50)
        
        return templates.TemplateResponse("users/detail.html", get_template_context(
            request, user=user, user_data=user_data,
            receipts=receipts, title=f"Пользователь #{user_id}",
            message=msg
        ))

    @router.post("/{user_id}/message", dependencies=[Depends(verify_csrf_token)])
    async def send_user_message(
        request: Request,
        user_id: int,
        text: str = Form(None),
        photo: UploadFile = File(None),
        user: str = Depends(get_current_user)
    ):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")
        
        user_data = await get_user_detail(user_id)
        if not user_data or user_data['bot_id'] != bot['id']:
            raise HTTPException(status_code=404, detail="User not found")

        content = {}
        if photo and photo.filename:
            ext = Path(photo.filename).suffix or ".jpg"
            filename = f"{uuid.uuid4()}{ext}"
            filepath = UPLOADS_DIR / filename
            async with aiofiles.open(filepath, 'wb') as f:
                while chunk := await photo.read(1024 * 1024):
                    await f.write(chunk)
            content["photo_path"] = str(filepath)
            content["caption"] = text
        elif text:
            content["text"] = text
        else:
            return RedirectResponse(url=f"/users/{user_id}?msg=error_empty", status_code=status.HTTP_303_SEE_OTHER)
        
        telegram_id = user_data['telegram_id']
        
        # Send message synchronously to provide feedback
        from aiogram import Bot as AiogramBot
        from aiogram.types import FSInputFile
        
        try:
            bot_instance = AiogramBot(token=bot['token'])
            if "photo_path" in content:
                await bot_instance.send_photo(telegram_id, FSInputFile(content["photo_path"]), caption=content.get("caption"))
            else:
                await bot_instance.send_message(telegram_id, content.get("text", ""))
                
            await bot_instance.session.close()
            logger.info(f"Direct message sent to user {telegram_id}")
            return RedirectResponse(url=f"/users/{user_id}?msg=sent", status_code=status.HTTP_303_SEE_OTHER)
            
        except Exception as e:
            logger.error(f"Failed to send message to {telegram_id}: {e}")
            await bot_instance.session.close()
            import urllib.parse
            error_text = urllib.parse.quote(str(e)[:100])
            return RedirectResponse(url=f"/users/{user_id}?msg=error&error_text={error_text}", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/{user_id}/add-receipt", dependencies=[Depends(verify_csrf_token)])
    async def add_user_receipt(request: Request, user_id: int, user: str = Depends(get_current_user)):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        user_data = await get_user_detail(user_id)
        if not user_data or user_data['bot_id'] != bot['id']:
            raise HTTPException(status_code=404, detail="User not found")
        
        ts = int(time.time())
        uid = str(uuid.uuid4())[:8]
        
        await add_receipt(
            user_id=user_id, status="valid",
            data={"manual": True, "admin": user, "source": "web_panel"},
            fiscal_drive_number="MANUAL",
            fiscal_document_number=f"MANUAL_{ts}_{uid}",
            fiscal_sign=f"MANUAL_{user_id}_{ts}",
            total_sum=0, raw_qr="manual_web",
            product_name="Ручное добавление (веб)"
        )
        
        return RedirectResponse(url=f"/users/{user_id}?msg=receipt_added", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/{user_id}/block", dependencies=[Depends(verify_csrf_token)])
    async def toggle_user_block(request: Request, user_id: int, user: str = Depends(get_current_user)):
        user_data = await get_user_detail(user_id)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        new_status = not user_data.get('is_blocked', False)
        await block_user(user_id, new_status)
        return RedirectResponse(url=f"/users/{user_id}?msg={'blocked' if new_status else 'unblocked'}", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/{user_id}/add-tickets", dependencies=[Depends(verify_csrf_token)])
    async def add_user_tickets(
        request: Request,
        user_id: int,
        tickets: int = Form(...),
        reason: str = Form(None),
        user: str = Depends(get_current_user)
    ):
        """Add manual tickets to a user"""
        from database.bot_methods import add_manual_tickets
        
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        user_data = await get_user_detail(user_id)
        if not user_data or user_data['bot_id'] != bot['id']:
            raise HTTPException(status_code=404, detail="User not found")
        
        if tickets < 1 or tickets > 10000:
            return RedirectResponse(url=f"/users/{user_id}?msg=tickets_error", status_code=status.HTTP_303_SEE_OTHER)
        
        await add_manual_tickets(user_id, tickets, reason, user)
        return RedirectResponse(url=f"/users/{user_id}?msg=tickets_added", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/{user_id}/update", dependencies=[Depends(verify_csrf_token)])
    async def update_user_profile(
        request: Request,
        user_id: int,
        full_name: str = Form(None),
        phone: str = Form(None),
        username: str = Form(None),
        user: str = Depends(get_current_user)
    ):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        user_data = await get_user_detail(user_id)
        if not user_data or user_data['bot_id'] != bot['id']:
            raise HTTPException(status_code=404, detail="User not found")

        full_name_clean = full_name.strip() if full_name else None
        phone_clean = phone.strip() if phone else None
        username_clean = username.strip().lstrip("@") if username else None

        await update_user_fields(
            user_id,
            full_name=full_name_clean or user_data.get("full_name"),
            phone=phone_clean or user_data.get("phone"),
            username=username_clean if username is not None else user_data.get("username"),
        )

        return RedirectResponse(url=f"/users/{user_id}?msg=updated", status_code=status.HTTP_303_SEE_OTHER)

    return router
