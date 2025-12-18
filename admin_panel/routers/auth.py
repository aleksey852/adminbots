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
    if not token:
        raise HTTPException(status_code=403, detail="CSRF token missing in session")
    
    # Fast path: header token to avoid parsing huge multipart bodies
    header_token = request.headers.get("X-CSRF-Token")
    if header_token and header_token == token:
        return

    form = await request.form()
    submitted_token = form.get("csrf_token") or header_token
    if not submitted_token or submitted_token != token:
        raise HTTPException(status_code=403, detail="CSRF token invalid")


def setup_routes(app_templates: Jinja2Templates):
    """Setup routes with templates reference"""
    templates = app_templates
    
    @router.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse("login.html", {"request": request, "csrf_token": get_csrf_token(request)})

    @router.post("/login")
    async def login(request: Request):
        import bcrypt
        from database.panel_db import get_panel_user
        from database import update_panel_user_login
        
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        
        # Get user from database
        panel_user = await get_panel_user(username)
        
        if panel_user:
            # Verify password with bcrypt
            if bcrypt.checkpw(password.encode('utf-8'), panel_user['password_hash'].encode('utf-8')):
                await update_panel_user_login(panel_user['id'])
                token = create_token(username, panel_user['role'])
                response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
                response.set_cookie("access_token", token, httponly=True, max_age=TOKEN_EXPIRE_HOURS * 3600)
                return response
        
        # Fallback to .env for backward compatibility
        if username == config.ADMIN_PANEL_USER and password == config.ADMIN_PANEL_PASSWORD:
            token = create_token(username, 'superadmin')
            response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
            response.set_cookie("access_token", token, httponly=True, max_age=TOKEN_EXPIRE_HOURS * 3600)
            return response
        
        return templates.TemplateResponse("login.html", {"request": request, "error": "Неверные данные", "csrf_token": get_csrf_token(request)})

    @router.get("/logout")
    async def logout():
        response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie("access_token")
        return response

    return router
