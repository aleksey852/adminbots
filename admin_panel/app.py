"""Admin Panel - FastAPI app with modular routers"""
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime, date
from pathlib import Path
from typing import Dict
import sys
import time
import logging

# Ensure project root is in path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config

# Panel DB for registry operations
from database.panel_db import (
    init_panel_db, close_panel_db,
    get_all_bots, get_bot_by_id, get_active_bots
)

# Bot DB for bot-specific operations
from database.bot_db import bot_db_manager

# Routers
from admin_panel.routers import auth, bots, users, campaigns, system, texts

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
ADMIN_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = ADMIN_DIR / "templates"
STATIC_DIR = ADMIN_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
UPLOADS_DIR = ADMIN_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# Timing constants
SLOW_REQUEST_THRESHOLD = 3.0


# === Lifespan ===

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await init_panel_db(config.PANEL_DATABASE_URL)
        
        # Register modules so they appear in settings
        from modules.base import module_loader
        from modules.core import core_module
        from modules.registration import registration_module
        from modules.receipts import receipts_module
        from modules.promo import promo_module
        from modules.admin import admin_module
        from modules.subscription import subscription_module
        
        module_loader.register(core_module)
        module_loader.register(registration_module)
        module_loader.register(receipts_module)
        module_loader.register(promo_module)
        module_loader.register(admin_module)
        module_loader.register(subscription_module)
        
        if config.ADMIN_PANEL_USER and config.ADMIN_PANEL_PASSWORD:
            import bcrypt
            from database.panel_db import ensure_initial_superadmin
            password_hash = bcrypt.hashpw(
                config.ADMIN_PANEL_PASSWORD.encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')
            await ensure_initial_superadmin(config.ADMIN_PANEL_USER, password_hash)
        
        logger.info("Panel database initialized")
    except Exception as e:
        logger.critical(f"Failed to initialize panel database: {e}")
    
    yield
    
    # Shutdown
    await close_panel_db()
    await bot_db_manager.close_all()


# === App Setup ===

app = FastAPI(title="Admin Bots Panel", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))




# === Middleware ===

@app.middleware("http")
async def context_middleware(request: Request, call_next):
    """Set active bot context and connect to its database"""
    start_time = time.time()
    
    # Load active bots
    try:
        bots_list = await get_active_bots()
        request.state.bots = bots_list
    except Exception as e:
        logger.error(f"Failed to load bots from registry: {e}")
        request.state.bots = []
    
    # Determine active bot
    active_bot_id = request.session.get("active_bot_id")
    active_bot = None
    
    if active_bot_id:
        active_bot = await get_bot_by_id(active_bot_id)
        if not active_bot:
            active_bot_id = None
            
    if not active_bot and request.state.bots:
        active_bot = request.state.bots[0]
        request.session["active_bot_id"] = active_bot['id']
    
    request.state.bot = active_bot
    
    # Connect to bot's database
    if active_bot and active_bot.get('database_url'):
        bot_id = active_bot['id']
        db_url = active_bot['database_url']
        
        if not bot_db_manager.get(bot_id):
            bot_db_manager.register(bot_id, db_url)
            
        # Always ensure connected (BotDatabase.connect handles idempotency)
        try:
            await bot_db_manager.connect(bot_id)
        except Exception as e:
            logger.error(f"Failed to connect to bot {bot_id} database: {e}")
        
        bot_db = bot_db_manager.get(bot_id)
        request.state.bot_db = bot_db
        
        # Set context for bot_methods
        if bot_db:
            from database import bot_methods
            bot_methods.set_current_bot_db(bot_db)
    else:
        request.state.bot_db = None
    
    # Log request
    bot_name = active_bot['name'] if active_bot else 'None'
    logger.info(f"➡️  {request.method} {request.url.path} (Bot: {bot_name})")
    
    try:
        response = await call_next(request)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"❌ Request failed: {request.method} {request.url.path} - {duration:.2f}s - {e}")
        raise
    
    duration = time.time() - start_time
    if duration > SLOW_REQUEST_THRESHOLD:
        logger.warning(f"🐢 Slow request: {duration:.2f}s")
    
    return response


# Add Session Middleware LAST so it wraps everything (including consumers of session)
app.add_middleware(SessionMiddleware, secret_key=config.ADMIN_SECRET_KEY)

# === Template Context Helper ===

def get_template_context(request: Request, **kwargs) -> Dict:
    """Helper to add common context variables"""
    user = kwargs.get('user', {})
    if isinstance(user, str):
        user = {'username': user, 'role': 'admin'}
    
    def has_module(module_name: str) -> bool:
        """Check if bot has module enabled"""
        if not request.state.bot:
            return False
        modules = request.state.bot.get('enabled_modules')
        if not modules:
            return False
        return module_name in modules

    context = {
        "request": request,
        "csrf_token": auth.get_csrf_token(request),
        "bot": request.state.bot,
        "bots": getattr(request.state, 'bots', []),
        "current_user": user,
        "is_superadmin": user.get('role') == 'superadmin' if user else False,
        "has_module": has_module,
    }
    context.update(kwargs)
    return context


# === Setup Routers ===

# Auth router (has special setup for templates)
auth.setup_routes(templates)
app.include_router(auth.router)

# Bots router
bots.setup_routes(
    templates,
    auth.get_current_user,
    auth.require_superadmin,
    auth.verify_csrf_token,
    get_template_context
)
app.include_router(bots.router)

# Users router
users.setup_routes(
    templates,
    auth.get_current_user,
    auth.verify_csrf_token,
    get_template_context,
    UPLOADS_DIR
)
app.include_router(users.router)

# Campaigns router
campaigns.setup_routes(
    templates,
    auth.get_current_user,
    auth.verify_csrf_token,
    get_template_context,
    UPLOADS_DIR
)
app.include_router(campaigns.router)



# System router
system.setup_routes(
    templates,
    auth.get_current_user,
    auth.require_superadmin,
    auth.verify_csrf_token,
    get_template_context,
    BASE_DIR
)
app.include_router(system.router)
 
 
 # Texts router
texts.setup_routes(
    templates,
    auth.get_current_user,
    auth.verify_csrf_token,
    get_template_context
)
app.include_router(texts.router)


# === Dashboard (main page) ===

from database import (
    get_stats, get_participants_count, get_stats_by_days, get_recent_campaigns
)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: Dict = Depends(auth.get_current_user)):
    bot = request.state.bot
    if not bot:
        return templates.TemplateResponse("dashboard.html", get_template_context(
            request, user=user, error="No active bot",
            stats={}, participants=0, daily_stats=[], recent_campaigns=[], title="Dashboard"
        ))

    bot_id = bot['id']
    stats = await get_stats()
    participants = await get_participants_count()
    daily_stats = await get_stats_by_days(days=14)
    
    # Convert dates
    for stat in daily_stats:
        if 'day' in stat and isinstance(stat['day'], (datetime, date)):
            stat['day'] = stat['day'].isoformat()
            
    recent = await get_recent_campaigns(limit=5)
    
    return templates.TemplateResponse("dashboard.html", get_template_context(
        request, user=user, stats=stats, participants=participants,
        daily_stats=daily_stats, recent_campaigns=recent,
        title="Dashboard"
    ))


# === Statistics API ===

from fastapi.responses import JSONResponse

@app.get("/api/stats/daily")
async def api_daily_stats(request: Request, days: int = 14, user: Dict = Depends(auth.get_current_user)):
    bot = request.state.bot
    if not bot:
        return JSONResponse({})
    
    data = await get_stats_by_days(days=days)
    return JSONResponse({
        "labels": [str(d['day']) for d in data],
        "users": [d['users'] for d in data],
        "receipts": [d['receipts'] for d in data]
    })


# === Bot switch endpoint (needs to be at root level) ===

@app.post("/bot/switch/{bot_id}", dependencies=[Depends(auth.verify_csrf_token)])
async def switch_bot(request: Request, bot_id: int, user: Dict = Depends(auth.get_current_user)):
    bot = await get_bot_by_id(bot_id)
    if bot:
        request.session["active_bot_id"] = bot_id
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)
