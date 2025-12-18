"""Authentication router: login, logout, token management"""
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional, Dict
import secrets

import config

router = APIRouter(tags=["auth"])

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


def create_token(username: str, role: str = 'admin') -> str:
    """Create JWT token for user"""
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "role": role, "exp": expire}, config.ADMIN_SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[Dict]:
    """Verify JWT token and return user data"""
    try:
        payload = jwt.decode(token, config.ADMIN_SECRET_KEY, algorithms=[ALGORITHM])
        return {"username": payload.get("sub"), "role": payload.get("role", "admin")}
    except JWTError:
        return None


async def get_current_user(request: Request) -> Dict:
    """Dependency: Returns dict with 'username' and 'role' keys"""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    user_data = verify_token(token)
    if not user_data:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user_data


async def require_superadmin(request: Request) -> Dict:
    """Dependency: Requires superadmin role"""
    user = await get_current_user(request)
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Доступ только для SuperAdmin")
    return user


def get_csrf_token(request: Request) -> str:
    """Get or create CSRF token"""
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token


async def verify_csrf_token(request: Request):
    """Verify CSRF token from form or header"""
    token = request.session.get("csrf_token")
    if not token: return # Relaxed for internal use
    
    submitted = (await request.form()).get("csrf_token") or request.headers.get("X-CSRF-Token")
    if submitted != token: raise HTTPException(403, "CSRF invalid")


def setup_routes(app_templates: Jinja2Templates):
    templates = app_templates
    
    @router.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse("login.html", {"request": request, "csrf_token": get_csrf_token(request)})

    @router.post("/login")
    async def login(request: Request):
        import bcrypt
        from database.panel_db import get_panel_user, update_panel_user_login
        
        form = await request.form()
        u, p = form.get("username"), form.get("password")
        
        # Check DB first, then fallback to .env
        user = await get_panel_user(u)
        if (user and bcrypt.checkpw(p.encode(), user['password_hash'].encode())) or (u == config.ADMIN_PANEL_USER and p == config.ADMIN_PANEL_PASSWORD):
            if user: await update_panel_user_login(user['id'])
            token = create_token(u, user['role'] if user else 'superadmin')
            resp = RedirectResponse("/", 303)
            resp.set_cookie("access_token", token, httponly=True, max_age=TOKEN_EXPIRE_HOURS * 3600)
            return resp
        
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid login", "csrf_token": get_csrf_token(request)})

    @router.get("/logout")
    async def logout():
        resp = RedirectResponse("/login", 303)
        resp.delete_cookie("access_token")
        return resp

    return router
