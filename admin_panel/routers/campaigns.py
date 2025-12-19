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
    get_all_receipts_paginated, get_total_receipts_count, get_all_recent_raffles
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
        if not (bot := request.state.bot) or bot.get("type") != "receipt": return RedirectResponse("/")
        
        total = await get_total_receipts_count()
        return templates.TemplateResponse("receipts/list.html", get_template_context(
            request, user=user, receipts=await get_all_receipts_paginated(page=page, per_page=50),
            page=page, total_pages=(total + 49) // 50, total=total, title="Чеки"
        ))

    @router.get("/winners", response_class=HTMLResponse)
    async def winners_list(request: Request, user: str = Depends(get_current_user)):
        if not request.state.bot: return RedirectResponse("/")
        return templates.TemplateResponse("winners/list.html", get_template_context(request, user=user, raffles=await get_recent_raffles_with_winners(10), title="Победители"))

    @router.get("/broadcast", response_class=HTMLResponse)
    async def broadcast_page(request: Request, user: str = Depends(get_current_user), created: str = None):
        if not request.state.bot: return RedirectResponse("/")
        recent = await get_recent_campaigns(10)
        return templates.TemplateResponse("broadcast/index.html", get_template_context(
            request, user=user, title="Рассылка", total_users=await get_total_users_count(),
            broadcasts=[c for c in recent if c['type'] == 'broadcast'], created=created
        ))

    @router.post("/broadcast/create", dependencies=[Depends(verify_csrf_token)])
    async def create_broadcast(
        request: Request, text: str = Form(None), photo: UploadFile = File(None),
        scheduled_for: str = Form(None), user: str = Depends(get_current_user)
    ):
        if not request.state.bot: return RedirectResponse("/")
        content = {}
        if photo and photo.filename:
            path = UPLOADS_DIR / f"{uuid.uuid4()}{Path(photo.filename).suffix or '.jpg'}"
            async with aiofiles.open(path, 'wb') as f:
                while chunk := await photo.read(1024*1024): await f.write(chunk)
            content.update({"photo_path": str(path), "caption": text})
        elif text and text.strip(): 
            content["text"] = text.strip()
        else: 
            # If no photo and no text (or empty text)
            raise HTTPException(400, "Message (text or photo) required")
        
        cid = await add_campaign("broadcast", content, config.parse_scheduled_time(scheduled_for) if scheduled_for else None)
        return RedirectResponse(f"/broadcast?created={cid}", 303)

    @router.get("/campaigns", response_class=HTMLResponse)
    async def campaigns_list(request: Request, user: str = Depends(get_current_user)):
        if not request.state.bot: return RedirectResponse("/")
        return templates.TemplateResponse("campaigns/list.html", get_template_context(request, user=user, campaigns=await get_recent_campaigns(50), title="Кампании"))

    @router.post("/campaigns/{cid}/cancel", dependencies=[Depends(verify_csrf_token)])
    async def cancel_campaign_route(request: Request, cid: int, user: str = Depends(get_current_user)):
        from database import cancel_campaign, bot_db_context
        if not (bot := request.state.bot): return RedirectResponse("/")
        
        async with bot_db_context(bot['id']):
            await cancel_campaign(cid)
            
        return RedirectResponse("/campaigns", 303)

    @router.get("/codes", response_class=HTMLResponse)
    async def codes_list(request: Request, user: str = Depends(get_current_user), page: int = 1, q: str = None):
        from database import get_promo_stats, get_promo_codes_paginated
        if not (bot := request.state.bot) or bot.get("type") != "promo": return RedirectResponse("/")
        return templates.TemplateResponse("codes/list.html", get_template_context(
            request, user=user, title="Промокоды", stats=await get_promo_stats(),
            codes=await get_promo_codes_paginated(50, (page-1)*50, search_query=q),
            search_query=q
        ))

    @router.post("/codes/upload", dependencies=[Depends(verify_csrf_token)])
    async def upload_codes(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
        import logging, shutil, asyncio
        logger = logging.getLogger(__name__)
        logger.info(f"📥 upload_codes: starting, file={file.filename}")
        
        from admin_panel.utils.importer import process_promo_import
        from database import create_job, bot_db_context
        if not (bot := request.state.bot) or bot.get("type") != "promo": 
            logger.error("Wrong bot type for promo upload")
            return JSONResponse({"error": "Wrong bot"}, 400)
        
        path = UPLOADS_DIR / f"imp_{bot['id']}_{int(time.time())}_{uuid.uuid4().hex[:6]}.txt"
        
        # Optimize file saving: use a thread pool for heavy I/O
        def save_file():
            with path.open('wb') as f:
                shutil.copyfileobj(file.file, f)
        
        try:
            logger.info(f"📝 Saving to {path}")
            await asyncio.to_thread(save_file)
            
            file_size = path.stat().st_size / 1024 / 1024
            logger.info(f"✅ File saved: {file_size:.2f} MB")
            
            async with bot_db_context(bot['id']):
                jid = await create_job('import_promo', {"file": path.name, "size_mb": round(file_size, 2)})
            
            logger.info(f"🚀 Job created: {jid}, starting background task")
            background_tasks.add_task(process_promo_import, str(path), bot['id'], jid)
            return JSONResponse({"status": "queued", "job_id": jid, "message": "Файл успешно принят, начинается обработка"})
        except Exception as e:
            logger.exception(f"❌ Upload error: {e}")
            return JSONResponse({"error": f"Ошибка сохранения: {str(e)}"}, 500)

    @router.get("/api/jobs/active")
    async def get_active_jobs_api(request: Request):
        from database import get_active_jobs, bot_db_context
        if not (bot := request.state.bot): return JSONResponse([])
        async with bot_db_context(bot['id']):
            jobs = await get_active_jobs()
        return JSONResponse([
            {
                **dict(j), 
                "details": json.loads(j['details']) if isinstance(j['details'], str) else j['details'], 
                "created_at": j['created_at'].isoformat(),
                "updated_at": j['updated_at'].isoformat()
            } for j in jobs
        ])

    @router.get("/api/jobs/{jid}")
    async def get_job_api(request: Request, jid: int):
        from database import get_job, bot_db_context
        if not (bot := request.state.bot): return JSONResponse({"error": "No bot"}, 404)
        async with bot_db_context(bot['id']):
            job = await get_job(jid)
        if not job: return JSONResponse({"error": "Not found"}, 404)
        return JSONResponse({
            **dict(job), 
            "details": json.loads(job['details']) if isinstance(job['details'], str) else job['details'], 
            "created_at": job['created_at'].isoformat(),
            "updated_at": job['updated_at'].isoformat()
        })

    @router.get("/raffle", response_class=HTMLResponse)
    async def raffle_page(request: Request, user: str = Depends(get_current_user), created: str = None):
        if not request.state.bot: return RedirectResponse("/")
        return templates.TemplateResponse("raffle/index.html", get_template_context(
            request, user=user, title="Розыгрыш", participants=await get_participants_count(),
            total_tickets=await get_total_tickets_count(), recent_raffles=await get_all_recent_raffles(5), created=created
        ))

    @router.post("/raffle/create", dependencies=[Depends(verify_csrf_token)])
    async def create_raffle(
        request: Request, 
        prize_names: list[str] = Form(None), winner_counts: list[int] = Form(None), 
        prize_msgs: list[str] = Form(None),
        # Fallback for old forms
        prize_name: str = Form(None), winner_count: int = Form(None),
        # Removed win_text/win_photo
        lose_text: str = Form(None), lose_photo: UploadFile = File(None),
        scheduled_for: str = Form(None), raffle_type: str = Form("intermediate"),
        user: str = Depends(get_current_user)
    ):
        if not request.state.bot: return RedirectResponse("/")
        
        async def save_media(file, prefix, text):
            text = (text or "").strip()  # Normalize empty/None to empty string
            if not (file and isinstance(file, UploadFile) and file.filename): 
                return {"text": text} if text else {}
            path = UPLOADS_DIR / f"{prefix}_{uuid.uuid4().hex[:8]}{Path(file.filename).suffix}"
            async with aiofiles.open(path, 'wb') as f:
                while chunk := await file.read(1024*1024): await f.write(chunk)
            res = {"photo_path": str(path)}
            if text: res["caption"] = text
            return res


        form_data = await request.form()
        
        # Parse prizes manually by index keys to ensure correct mapping
        # Keys are like: prize_names, winner_counts, prize_msgs - usually lists
        # But we also have prize_photo_{i} which relies on index.
        # Safer to iterate indices based on prize_names list length from form.
        
        # Get raw validation lists
        raw_names = form_data.getlist("prize_names")
        raw_counts = form_data.getlist("winner_counts")
        raw_msgs = form_data.getlist("prize_msgs")
        
        prizes = []
        if raw_names and raw_counts:
            # We assume the frontend maintains parallel array order
            count_len = min(len(raw_names), len(raw_counts))
            
            for i in range(count_len):
                name = raw_names[i].strip()
                try:
                    count = int(raw_counts[i])
                except ValueError:
                    count = 0
                
                if name and count > 0:
                    prize_data = {"name": name, "count": count}
                    
                    # Prize Text (safe index access)
                    if i < len(raw_msgs) and raw_msgs[i].strip():
                        prize_data["msg"] = raw_msgs[i].strip()
                    
                    # Prize Photo (prize_photo_{i})
                    # Note: index i corresponds to the DOM order.
                    photo_key = f"prize_photo_{i}"
                    photo_file = form_data.get(photo_key)
                    
                    if isinstance(photo_file, UploadFile) and photo_file.filename:
                        saved = await save_media(photo_file, f"prize_{i}", None)
                        if "photo_path" in saved:
                            prize_data["photo_path"] = saved["photo_path"]

                    prizes.append(prize_data)
        


        if not prizes:
             raise HTTPException(400, "At least one prize required")

        # Determine raffle type flags
        is_final = (raffle_type == "final")
        burn_tickets = (raffle_type == "intermediate")

        content = {
            "prizes": prizes, # List of prizes
            "prize": prizes[0]["name"], # Backward compat
            "count": prizes[0]["count"], # Backward compat
            "is_final": is_final,
            "burn_tickets": burn_tickets,  # New: burn tickets after intermediate raffle
            # Removed win_msg global fallback
            "lose_msg": await save_media(lose_photo, "lose", lose_text)
        }
        
        cid = await add_campaign("raffle", content, config.parse_scheduled_time(scheduled_for) if scheduled_for else None)
        return RedirectResponse(f"/raffle?created={cid}", 303)
    return router
