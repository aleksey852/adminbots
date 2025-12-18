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
        backup_dir = get_backup_dir()
        backups = []
        
        if backup_dir.exists():
            for file in sorted(backup_dir.glob("backup_*.sql.gz"), reverse=True):
                stat = file.stat()
                backups.append({
                    "filename": file.name,
                    "size": stat.st_size,
                    "size_mb": round(stat.st_size / 1024 / 1024, 2),
                    "created": datetime.fromtimestamp(stat.st_mtime),
                    "path": str(file)
                })
        
        total_size_mb = sum(b['size_mb'] for b in backups)
        disk_free_mb = round(shutil.disk_usage(backup_dir).free / 1024 / 1024, 2)
        
        return templates.TemplateResponse("backups/list.html", get_template_context(
            request, user=user, title="Резервные копии",
            backups=backups, total_size_mb=total_size_mb, disk_free_mb=disk_free_mb,
            backup_path=str(backup_dir)
        ))

    @router.post("/backups/create", dependencies=[Depends(verify_csrf_token)])
    async def create_backup_handler(request: Request, user: str = Depends(get_current_user)):
        backup_dir = get_backup_dir()
        script_path = BASE_DIR / "scripts" / "backup.sh"
        
        try:
            result = subprocess.run(
                ["bash", str(script_path), str(backup_dir)],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Backup created: {result.stdout}")
            return RedirectResponse(url="/backups?created=1", status_code=status.HTTP_303_SEE_OTHER)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Backup failed: {e.stderr}")
            return RedirectResponse(url="/backups?error=1", status_code=status.HTTP_303_SEE_OTHER)
        except Exception as e:
            logger.critical(f"Backup execution error: {e}")
            return RedirectResponse(url="/backups?error=1", status_code=status.HTTP_303_SEE_OTHER)

    # === Panel Users Management ===
    
    @router.get("/panel-users", response_class=HTMLResponse)
    async def panel_users_list(request: Request, user: Dict = Depends(require_superadmin), msg: str = None):
        from database.panel_db import get_all_panel_users
        
        users = await get_all_panel_users()
        message = None
        if msg == "created":
            message = "Пользователь создан"
        elif msg == "updated":
            message = "Пользователь обновлён"
        elif msg == "deleted":
            message = "Пользователь удалён"
        elif msg == "error_last_superadmin":
            message = "Нельзя удалить последнего SuperAdmin"
        elif msg == "error_exists":
            message = "Пользователь с таким логином уже существует"
        
        return templates.TemplateResponse("panel_users/list.html", get_template_context(
            request, user=user, title="Пользователи панели",
            users=users, message=message
        ))

    @router.post("/panel-users/create", dependencies=[Depends(verify_csrf_token)])
    async def panel_users_create(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        role: str = Form("admin"),
        user: Dict = Depends(require_superadmin)
    ):
        import bcrypt
        from database.panel_db import get_panel_user, create_panel_user
        
        existing = await get_panel_user(username)
        if existing:
            return RedirectResponse(url="/panel-users?msg=error_exists", status_code=status.HTTP_303_SEE_OTHER)
        
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        await create_panel_user(username, password_hash, role)
        
        return RedirectResponse(url="/panel-users?msg=created", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/panel-users/update", dependencies=[Depends(verify_csrf_token)])
    async def panel_users_update(
        request: Request,
        user_id: int = Form(...),
        username: str = Form(...),
        password: str = Form(""),
        role: str = Form("admin"),
        user: Dict = Depends(require_superadmin)
    ):
        import bcrypt
        from database.panel_db import update_panel_user
        
        password_hash = None
        if password.strip():
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        await update_panel_user(user_id, username=username, password_hash=password_hash, role=role)
        
        return RedirectResponse(url="/panel-users?msg=updated", status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/panel-users/{user_id}/delete", dependencies=[Depends(verify_csrf_token)])
    async def panel_users_delete(
        request: Request,
        user_id: int,
        user: Dict = Depends(require_superadmin)
    ):
        from database.panel_db import get_panel_user_by_id, delete_panel_user, count_superadmins
        
        target_user = await get_panel_user_by_id(user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if target_user['role'] == 'superadmin':
            superadmin_count = await count_superadmins()
            if superadmin_count <= 1:
                return RedirectResponse(url="/panel-users?msg=error_last_superadmin", status_code=status.HTTP_303_SEE_OTHER)
        
        await delete_panel_user(user_id)
        
        return RedirectResponse(url="/panel-users?msg=deleted", status_code=status.HTTP_303_SEE_OTHER)

    # === Domain & SSL Setup ===
    
    @router.get("/domain", response_class=HTMLResponse)
    async def domain_page(request: Request, user: Dict = Depends(require_superadmin), msg: str = None):
        import socket
        
        try:
            server_ip = subprocess.run(
                ["curl", "-s", "--max-time", "3", "ifconfig.me"],
                capture_output=True, text=True
            ).stdout.strip() or socket.gethostbyname(socket.gethostname())
        except Exception:
            server_ip = "Не определён"
        
        domain_file = BASE_DIR / ".domain"
        current_domain = None
        if domain_file.exists():
            current_domain = domain_file.read_text().strip()
        
        ssl_status = False
        if current_domain:
            cert_path = Path(f"/etc/letsencrypt/live/{current_domain}/fullchain.pem")
            ssl_status = cert_path.exists()
        
        logs = None
        logs_file = BASE_DIR / ".domain_logs"
        if logs_file.exists():
            logs = logs_file.read_text()
        
        message = None
        if msg == "success":
            message = "Домен настроен успешно!"
        elif msg == "error":
            message = "Ошибка при настройке домена. Проверьте логи."
        elif msg == "dns_pending":
            message = "Nginx настроен. Дождитесь обновления DNS для получения SSL."
        
        return templates.TemplateResponse("domain/index.html", get_template_context(
            request, user=user, title="Настройка домена",
            server_ip=server_ip, current_domain=current_domain,
            ssl_status=ssl_status, logs=logs, message=message
        ))

    @router.post("/domain/setup", dependencies=[Depends(verify_csrf_token)])
    async def domain_setup(
        request: Request,
        domain: str = Form(...),
        email: str = Form(""),
        user: Dict = Depends(require_superadmin)
    ):
        import re
        
        domain = domain.strip().lower()
        if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$', domain):
            return RedirectResponse(url="/domain?msg=error", status_code=status.HTTP_303_SEE_OTHER)
        
        script_path = BASE_DIR / "scripts" / "setup_domain.sh"
        
        if not script_path.exists():
            logger.error(f"Domain setup script not found: {script_path}")
            return RedirectResponse(url="/domain?msg=error", status_code=status.HTTP_303_SEE_OTHER)
        
        logs_file = BASE_DIR / ".domain_logs"
        
        try:
            cmd = ["sudo", "bash", str(script_path), domain]
            if email:
                cmd.append(email)
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            logs = f"=== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            logs += f"Command: {' '.join(cmd)}\n\n"
            logs += result.stdout
            if result.stderr:
                logs += f"\nSTDERR:\n{result.stderr}"
            logs_file.write_text(logs)
            
            if result.returncode == 0:
                domain_file = BASE_DIR / ".domain"
                domain_file.write_text(domain)
                return RedirectResponse(url="/domain?msg=success", status_code=status.HTTP_303_SEE_OTHER)
            elif "DNS" in result.stdout or "does not resolve" in result.stdout:
                return RedirectResponse(url="/domain?msg=dns_pending", status_code=status.HTTP_303_SEE_OTHER)
            else:
                return RedirectResponse(url="/domain?msg=error", status_code=status.HTTP_303_SEE_OTHER)
                
        except subprocess.TimeoutExpired:
            logs_file.write_text("Timeout: Script took too long to execute")
            return RedirectResponse(url="/domain?msg=error", status_code=status.HTTP_303_SEE_OTHER)
        except Exception as e:
            logger.error(f"Domain setup error: {e}")
            logs_file.write_text(f"Error: {e}")
            return RedirectResponse(url="/domain?msg=error", status_code=status.HTTP_303_SEE_OTHER)

    # === Logs Viewer ===
    
    @router.get("/settings/logs", response_class=HTMLResponse)
    async def logs_page(
        request: Request,
        service: str = "admin_bots",
        q: str = None,
        level: str = None,
        lines: int = 100,
        user: Dict = Depends(require_superadmin)
    ):
        if service not in ["admin_bots", "admin_panel"]:
            service = "admin_bots"
        
        lines = max(50, min(500, lines))
            
        cmd = ["journalctl", "-n", str(lines), "-u", service, "--no-pager"]
        
        if q:
            cmd += ["-g", q]
        
        if level:
            level_map = {"error": "3", "warning": "4", "info": "6"}
            if level in level_map:
                cmd += ["-p", level_map[level]]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logs = result.stdout
        except Exception as e:
            logs = (
                f"❌ Ошибка доступа к логам: {e}\n\n"
                f"Для исправления выполните на сервере:\n"
                f"sudo usermod -aG systemd-journal adminbots\n"
                f"sudo systemctl restart admin_panel\n\n"
                f"Затем обновите страницу."
            )
            
        return templates.TemplateResponse("settings/logs.html", get_template_context(
            request, user=user, title="Логи системы",
            logs=logs, active_service=service, q=q, active_level=level, lines=lines
        ))

    # === Server Migration Guide ===
    
    @router.get("/migration", response_class=HTMLResponse)
    async def migration_page(request: Request, user: Dict = Depends(require_superadmin)):
        import socket
        
        try:
            server_ip = subprocess.run(
                ["curl", "-s", "--max-time", "3", "ifconfig.me"],
                capture_output=True, text=True
            ).stdout.strip() or socket.gethostbyname(socket.gethostname())
        except Exception:
            server_ip = "Не определён"
        
        domain_file = BASE_DIR / ".domain"
        current_domain = domain_file.read_text().strip() if domain_file.exists() else None
        
        return templates.TemplateResponse("migration/index.html", get_template_context(
            request, user=user, title="Миграция сервера",
            server_ip=server_ip, current_domain=current_domain
        ))

    return router
