"""System router: backups, panel users, domain, logs, migration"""
from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime
from typing import Dict
import logging
import subprocess
import shutil

import config

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])

# Will be set by setup_routes
templates = None
get_current_user = None
require_superadmin = None
verify_csrf_token = None
get_template_context = None
BASE_DIR = None


def get_backup_dir() -> Path:
    """Get writable backup directory"""
    var_dir = Path("/var/backups/admin-bots-platform")
    try:
        if not var_dir.exists():
            var_dir.mkdir(parents=True, exist_ok=True)
        test_file = var_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        return var_dir
    except (PermissionError, Exception):
        local_dir = BASE_DIR / "backups"
        local_dir.mkdir(exist_ok=True)
        return local_dir


def setup_routes(
    app_templates: Jinja2Templates,
    auth_get_current_user,
    auth_require_superadmin,
    auth_verify_csrf_token,
    context_helper,
    base_dir: Path
):
    """Setup routes with dependencies"""
    global templates, get_current_user, require_superadmin, verify_csrf_token, get_template_context, BASE_DIR
    templates = app_templates
    get_current_user = auth_get_current_user
    require_superadmin = auth_require_superadmin
    verify_csrf_token = auth_verify_csrf_token
    get_template_context = context_helper
    BASE_DIR = base_dir

    # === Backups ===
    
    @router.get("/backups", response_class=HTMLResponse)
    async def backups_list(request: Request, user: Dict = Depends(require_superadmin)):
        dir = get_backup_dir()
        backups = []
        total_size_mb = 0.0
        if dir.exists():
            for f in sorted(dir.glob("backup_*.sql.gz"), reverse=True):
                size_mb = round(f.stat().st_size / 1024 / 1024, 2)
                backups.append({
                    "filename": f.name, 
                    "size_mb": size_mb, 
                    "created": datetime.fromtimestamp(f.stat().st_mtime),
                    "path": str(f)
                })
                total_size_mb += size_mb
        return templates.TemplateResponse("backups/list.html", get_template_context(
            request, user=user, title="Бэкапы", 
            backups=backups, 
            total_size_mb=round(total_size_mb, 2),
            disk_free_mb=round(shutil.disk_usage(dir).free / 1024 / 1024, 2)
        ))

    @router.post("/backups/create", dependencies=[Depends(verify_csrf_token)])
    async def create_backup_handler(request: Request):
        try:
            subprocess.run(["bash", str(BASE_DIR/"scripts"/"backup.sh"), str(get_backup_dir())], check=True)
            return RedirectResponse("/backups?created=1", 303)
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return RedirectResponse("/backups?error=1", 303)

    @router.get("/panel-users", response_class=HTMLResponse)
    async def panel_users_list(request: Request, user: Dict = Depends(require_superadmin), msg: str = None):
        from database.panel_db import get_all_panel_users
        return templates.TemplateResponse("panel_users/list.html", get_template_context(request, user=user, title="Пользователи", users=await get_all_panel_users(), message=msg))

    @router.post("/panel-users/create", dependencies=[Depends(verify_csrf_token)])
    async def panel_users_create(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form("admin")):
        import bcrypt
        from database.panel_db import get_panel_user, create_panel_user
        if await get_panel_user(username): return RedirectResponse("/panel-users?msg=error_exists", 303)
        await create_panel_user(username, bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), role)
        return RedirectResponse("/panel-users?msg=created", 303)

    @router.post("/panel-users/update", dependencies=[Depends(verify_csrf_token)])
    async def panel_users_update(request: Request, user_id: int = Form(...), username: str = Form(...), password: str = Form(""), role: str = Form("admin")):
        import bcrypt
        from database.panel_db import update_panel_user
        h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode() if password.strip() else None
        await update_panel_user(user_id, username=username, password_hash=h, role=role)
        return RedirectResponse("/panel-users?msg=updated", 303)

    @router.post("/panel-users/{user_id}/delete", dependencies=[Depends(verify_csrf_token)])
    async def panel_users_delete(request: Request, user_id: int):
        from database.panel_db import get_panel_user_by_id, delete_panel_user, count_superadmins
        u = await get_panel_user_by_id(user_id)
        if u and u['role'] == 'superadmin' and (await count_superadmins()) <= 1:
            return RedirectResponse("/panel-users?msg=error_last_superadmin", 303)
        await delete_panel_user(user_id)
        return RedirectResponse("/panel-users?msg=deleted", 303)

    @router.get("/domain", response_class=HTMLResponse)
    async def domain_page(request: Request, user: Dict = Depends(require_superadmin), msg: str = None):
        f = BASE_DIR / ".domain"
        dom = f.read_text().strip() if f.exists() else None
        ssl = Path(f"/etc/letsencrypt/live/{dom}/fullchain.pem").exists() if dom else False
        return templates.TemplateResponse("domain/index.html", get_template_context(request, user=user, title="Домен", current_domain=dom, ssl_status=ssl, logs=(BASE_DIR/".domain_logs").read_text() if (BASE_DIR/".domain_logs").exists() else None, message=msg))

    @router.post("/domain/setup", dependencies=[Depends(verify_csrf_token)])
    async def domain_setup(request: Request, domain: str = Form(...), email: str = Form("")):
        import logging
        logger = logging.getLogger(__name__)
        path = BASE_DIR / "scripts" / "setup_domain.sh"
        try:
            res = subprocess.run(["sudo", "bash", str(path), domain.strip().lower(), email], capture_output=True, text=True, timeout=120)
            output = res.stdout + (res.stderr or "")
            (BASE_DIR/".domain_logs").write_text(output)
            logger.info(f"Domain setup exit code: {res.returncode}, output length: {len(output)}")
            
            # Check for specific outcomes
            if res.returncode == 0:
                # Check if it's a DNS warning (script exits 0 but DNS not configured)
                if "DNS propagation" in output or "does not resolve" in output:
                    (BASE_DIR/".domain").write_text(domain.strip().lower())
                    return RedirectResponse("/domain?msg=dns_pending", 303)
                (BASE_DIR/".domain").write_text(domain.strip().lower())
                return RedirectResponse("/domain?msg=success", 303)
            else:
                logger.error(f"Domain setup failed: {output[-500:]}")
                return RedirectResponse("/domain?msg=error", 303)
        except subprocess.TimeoutExpired:
            (BASE_DIR/".domain_logs").write_text("Timeout: скрипт выполнялся более 120 сек")
            return RedirectResponse("/domain?msg=timeout", 303)
        except Exception as e:
            logger.error(f"Domain setup exception: {e}")
            (BASE_DIR/".domain_logs").write_text(str(e))
            return RedirectResponse("/domain?msg=error", 303)

    @router.get("/settings/logs", response_class=HTMLResponse)
    async def logs_page(request: Request, service: str = "admin_bots", q: str = None, level: str = None, lines: int = 100, user: Dict = Depends(require_superadmin)):
        cmd = ["journalctl", "-n", str(max(50, min(500, lines))), "-u", service if service in ["admin_bots", "admin_panel"] else "admin_bots", "--no-pager"]
        if q: cmd += ["-g", q]
        if level in {"error": "3", "warning": "4", "info": "6"}: cmd += ["-p", {"error": "3", "warning": "4", "info": "6"}[level]]
        try:
            logs = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        except Exception as e:
            logs = f"Похоже, у пользователя 'adminbots' нет прав на чтение журналов systemd.\n\n" \
                   f"Ошибка: {e}\n\n" \
                   f"Для исправления выполните на сервере:\n" \
                   f"sudo usermod -aG systemd-journal adminbots\n" \
                   f"sudo systemctl restart admin_panel"
        return templates.TemplateResponse("settings/logs.html", get_template_context(request, user=user, title="Логи", logs=logs, active_service=service, q=q, active_level=level, lines=lines))

    @router.get("/migration", response_class=HTMLResponse)
    async def migration_page(request: Request, user: Dict = Depends(require_superadmin)):
        f = BASE_DIR / ".domain"
        return templates.TemplateResponse("migration/index.html", get_template_context(request, user=user, title="Миграция", current_domain=f.read_text().strip() if f.exists() else None))

    return router
