"""Campaigns router: broadcasts, raffles, promo codes"""
from fastapi import APIRouter, Request, Depends, HTTPException, status, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Dict
import logging
import uuid
import json
import time
import aiofiles

import config
from database import (
    get_total_users_count, get_recent_campaigns, add_campaign,
    get_participants_count, get_total_tickets_count, get_recent_raffles_with_winners,
    get_all_receipts_paginated, get_total_receipts_count
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["campaigns"])

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

    # === Receipts ===
    
    @router.get("/receipts", response_class=HTMLResponse)
    async def receipts_list(request: Request, user: str = Depends(get_current_user), page: int = 1):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")
        if bot.get("type") != "receipt":
            return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

        receipts = await get_all_receipts_paginated(page=page, per_page=50)
        total = await get_total_receipts_count()
        total_pages = (total + 49) // 50
        return templates.TemplateResponse("receipts/list.html", get_template_context(
            request, user=user, receipts=receipts,
            page=page, total_pages=total_pages, total=total,
            title="Чеки"
        ))

    # === Winners ===
    
    @router.get("/winners", response_class=HTMLResponse)
    async def winners_list(request: Request, user: str = Depends(get_current_user)):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        raffles = await get_recent_raffles_with_winners(limit=10)
        return templates.TemplateResponse("winners/list.html", get_template_context(
            request, user=user, raffles=raffles, title="Победители"
        ))

    # === Broadcast ===
    
    @router.get("/broadcast", response_class=HTMLResponse)
    async def broadcast_page(request: Request, user: str = Depends(get_current_user), created: str = None):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        total_users = await get_total_users_count()
        recent = await get_recent_campaigns(10)
        broadcasts = [c for c in recent if c['type'] == 'broadcast']
        
        return templates.TemplateResponse("broadcast/index.html", get_template_context(
            request, user=user, title="Рассылка",
            total_users=total_users, broadcasts=broadcasts,
            created=created
        ))

    @router.post("/broadcast/create", dependencies=[Depends(verify_csrf_token)])
    async def create_broadcast(
        request: Request,
        text: str = Form(None),
        photo: UploadFile = File(None),
        scheduled_for: str = Form(None),
        user: str = Depends(get_current_user)
    ):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        content = {}
        try:
            if photo and photo.filename:
                ext = Path(photo.filename).suffix or ".jpg"
                filename = f"{uuid.uuid4()}{ext}"
                filepath = UPLOADS_DIR / filename
                async with aiofiles.open(filepath, 'wb') as f:
                    while chunk := await photo.read(1024 * 1024):
                        await f.write(chunk)
                content["photo_path"] = str(filepath)
                content["caption"] = text
            elif text and text.strip():
                content["text"] = text.strip()
            else:
                raise HTTPException(status_code=400, detail="Message required")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error saving broadcast file: {e}")
            raise HTTPException(status_code=500, detail="Failed to save file")
        
        schedule_dt = None
        if scheduled_for and scheduled_for.strip():
            schedule_dt = config.parse_scheduled_time(scheduled_for)
        
        campaign_id = await add_campaign("broadcast", content, schedule_dt)
        return RedirectResponse(url=f"/broadcast?created={campaign_id}", status_code=status.HTTP_303_SEE_OTHER)

    # === All Campaigns ===
    
    @router.get("/campaigns", response_class=HTMLResponse)
    async def campaigns_list(request: Request, user: str = Depends(get_current_user), page: int = 1):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")
        
        campaigns = await get_recent_campaigns(limit=50)
        
        return templates.TemplateResponse("campaigns/list.html", get_template_context(
            request, user=user, campaigns=campaigns,
            title="Кампании"
        ))

    # === Promo Codes ===
    
    @router.get("/codes", response_class=HTMLResponse)
    async def codes_list(request: Request, user: str = Depends(get_current_user), page: int = 1):
        from database import get_promo_stats, get_promo_codes_paginated
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")
        if bot.get("type") != "promo":
            return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        
        stats = await get_promo_stats()
        codes = await get_promo_codes_paginated(limit=50, offset=(page-1)*50)
        
        return templates.TemplateResponse("codes/list.html", get_template_context(
            request, user=user, title="Промокоды",
            stats=stats, codes=codes
        ))

    @router.post("/codes/upload", dependencies=[Depends(verify_csrf_token)])
    async def upload_codes(
        request: Request,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        user: str = Depends(get_current_user)
    ):
        from admin_panel.utils.importer import process_promo_import
        from database import create_job
        bot = request.state.bot
        if not bot or bot.get("type") != "promo":
            return JSONResponse({"status": "error", "message": "Bot not found or unsupported"}, status_code=400)
        
        logger.info(f"[codes/upload] start bot={bot['id']} filename={file.filename}")
        
        try:
            temp_dir = UPLOADS_DIR / "temp_imports"
            temp_dir.mkdir(exist_ok=True)
            temp_path = temp_dir / f"import_{bot['id']}_{int(time.time())}_{uuid.uuid4()}.txt"
            
            async with aiofiles.open(temp_path, 'wb') as out_file:
                while content := await file.read(1024 * 1024):
                    await out_file.write(content)
            
            file_size_mb = round(temp_path.stat().st_size / 1024 / 1024, 2)
            logger.info(f"[codes/upload] saved file {temp_path} size={file_size_mb}MB bot={bot['id']}")
            
            job_id = await create_job('import_promo', {"file": temp_path.name, "size_mb": file_size_mb})
            
            background_tasks.add_task(process_promo_import, str(temp_path), bot['id'], job_id)
            
            return JSONResponse({
                "status": "queued",
                "message": f"Файл загружен ({file_size_mb} MB). Импорт #{job_id} запущен в фоне.",
                "job_id": job_id
            })
            
        except Exception as e:
            logger.error(f"[codes/upload] error: {e}", exc_info=True)
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    @router.post("/codes/generate", dependencies=[Depends(verify_csrf_token)])
    async def generate_codes(
        request: Request,
        quantity: int = Form(...),
        tickets: int = Form(1),
        user: str = Depends(get_current_user)
    ):
        """Generate promo codes: save to DB + return as downloadable file"""
        from database import add_promo_codes
        from fastapi.responses import StreamingResponse
        import secrets
        import io
        from datetime import datetime
        
        bot = request.state.bot
        if not bot or bot.get("type") != "promo":
            return JSONResponse({"status": "error", "message": "Bot not found or unsupported"}, status_code=400)
        
        # Validate quantity
        if quantity < 1:
            return JSONResponse({"status": "error", "message": "Количество должно быть больше 0"}, status_code=400)
        if quantity > 100000:
            return JSONResponse({"status": "error", "message": "Максимум 100 000 кодов за раз"}, status_code=400)
        
        # Character set (no ambiguous chars like 0/O, 1/I/L, B/8)
        CHAR_SET = 'ACDEFGHJKLMNPRSTUVWXYZ2345679'
        CODE_LENGTH = 12
        
        logger.info(f"[codes/generate] Generating {quantity} codes for bot {bot['id']}")
        
        try:
            # Generate unique codes using cryptographically secure random
            generated_codes = set()
            max_attempts = quantity * 3
            attempts = 0
            
            while len(generated_codes) < quantity and attempts < max_attempts:
                code = ''.join(secrets.choice(CHAR_SET) for _ in range(CODE_LENGTH))
                generated_codes.add(code)
                attempts += 1
            
            codes_list = list(generated_codes)[:quantity]
            
            # Save to database
            added = await add_promo_codes(codes_list, tickets)
            
            logger.info(f"[codes/generate] Generated {len(codes_list)}, added {added} codes for bot {bot['id']}")
            
            # Create file content
            file_content = '\n'.join(codes_list)
            file_bytes = file_content.encode('utf-8')
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"promo_codes_{quantity}_{timestamp}.txt"
            
            # Return as downloadable file
            return StreamingResponse(
                io.BytesIO(file_bytes),
                media_type="text/plain",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "X-Codes-Added": str(added),
                    "X-Codes-Generated": str(len(codes_list))
                }
            )
            
        except Exception as e:
            logger.error(f"[codes/generate] error: {e}", exc_info=True)
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    # === Jobs API ===
    
    @router.get("/api/jobs/active")
    async def get_active_jobs_api(request: Request, user: str = Depends(get_current_user)):
        from database import get_active_jobs
        bot = request.state.bot
        if not bot:
            return JSONResponse([])
        
        jobs = await get_active_jobs()
        return JSONResponse([
            {
                "id": j['id'],
                "type": j['type'],
                "status": j['status'],
                "progress": j['progress'],
                "details": json.loads(j['details']) if isinstance(j['details'], str) else j['details'],
                "created_at": j['created_at'].isoformat() if j['created_at'] else None
            } for j in jobs
        ])

    @router.get("/api/jobs/{job_id}")
    async def get_job_api(job_id: int, request: Request, user: str = Depends(get_current_user)):
        from database import get_job
        bot = request.state.bot
        if not bot:
            return JSONResponse({"detail": "Bot not found"}, status_code=400)

        job = await get_job(job_id)
        if not job:
            return JSONResponse({"detail": "Job not found"}, status_code=404)

        details = json.loads(job['details']) if isinstance(job['details'], str) else job['details']
        return JSONResponse({
            "id": job['id'],
            "type": job['type'],
            "status": job['status'],
            "progress": job['progress'],
            "details": details,
            "created_at": job['created_at'].isoformat() if job['created_at'] else None,
            "updated_at": job['updated_at'].isoformat() if job['updated_at'] else None,
        })

    # === Raffle ===
    
    @router.get("/raffle", response_class=HTMLResponse)
    async def raffle_page(request: Request, user: str = Depends(get_current_user), created: str = None):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        participants = await get_participants_count()
        total_tickets = await get_total_tickets_count()
        recent_raffles = await get_recent_raffles_with_winners(limit=5)
        
        return templates.TemplateResponse("raffle/index.html", get_template_context(
            request, user=user, title="Розыгрыш",
            participants=participants, total_tickets=total_tickets,
            recent_raffles=recent_raffles, created=created
        ))

    @router.post("/raffle/create", dependencies=[Depends(verify_csrf_token)])
    async def create_raffle(
        request: Request,
        prize_name: str = Form(...),
        winner_count: int = Form(...),
        win_text: str = Form(None),
        win_photo: UploadFile = File(None),
        lose_text: str = Form(None),
        lose_photo: UploadFile = File(None),
        scheduled_for: str = Form(None),
        is_final: bool = Form(False),
        user: str = Depends(get_current_user)
    ):
        bot = request.state.bot
        if not bot:
            return RedirectResponse("/")

        win_msg = {}
        if win_photo and win_photo.filename:
            ext = Path(win_photo.filename).suffix or ".jpg"
            filename = f"win_{uuid.uuid4()}{ext}"
            filepath = UPLOADS_DIR / filename
            async with aiofiles.open(filepath, 'wb') as f:
                while content := await win_photo.read(1024 * 1024):
                    await f.write(content)
            win_msg["photo_path"] = str(filepath)
            win_msg["caption"] = win_text
        elif win_text:
            win_msg["text"] = win_text
        else:
            win_msg["text"] = f"🎉 Поздравляем! Вы выиграли: {prize_name}!"
        
        lose_msg = {}
        if lose_photo and lose_photo.filename:
            ext = Path(lose_photo.filename).suffix or ".jpg"
            filename = f"lose_{uuid.uuid4()}{ext}"
            filepath = UPLOADS_DIR / filename
            async with aiofiles.open(filepath, 'wb') as f:
                while content := await lose_photo.read(1024 * 1024):
                    await f.write(content)
            lose_msg["photo_path"] = str(filepath)
            lose_msg["caption"] = lose_text
        elif lose_text:
            lose_msg["text"] = lose_text
        
        content = {
            "prize": prize_name,
            "prize_name": prize_name,
            "count": winner_count,
            "win_msg": win_msg,
            "lose_msg": lose_msg,
            "is_final": is_final
        }
        
        schedule_dt = None
        if scheduled_for and scheduled_for.strip():
            schedule_dt = config.parse_scheduled_time(scheduled_for)
        
        campaign_id = await add_campaign("raffle", content, schedule_dt)
        return RedirectResponse(url=f"/raffle?created={campaign_id}", status_code=status.HTTP_303_SEE_OTHER)

    return router
