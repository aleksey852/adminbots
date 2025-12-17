#!/bin/bash
# Admin Bots Platform - Fix 502 Errors
# Usage: sudo bash scripts/fix_502.sh

set -e

PROJECT_DIR="/opt/admin-bots-platform"
SERVICE_USER="adminbots"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

[[ $EUID -ne 0 ]] && err "Run as root: sudo bash scripts/fix_502.sh"

log "=== Fixing 502 Errors ==="

# Stop services
log "Stopping admin panel..."
systemctl stop admin_panel || true

# Check if project exists
if [ ! -d "$PROJECT_DIR" ]; then
    err "Project directory not found: $PROJECT_DIR"
fi

# Update systemd service with more workers and timeout
log "Updating systemd service..."
cat > /etc/systemd/system/admin_panel.service << EOF
[Unit]
Description=Admin Bots Panel
After=network.target postgresql.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
Environment="PYTHONPATH=$PROJECT_DIR"
ExecStart=$PROJECT_DIR/venv/bin/uvicorn admin_panel.app:app --host 127.0.0.1 --port 8000 --workers 4 --timeout-keep-alive 120
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
LimitNOFILE=65535
LimitNPROC=4096
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Update nginx config if exists
NGINX_CONF="/etc/nginx/sites-available/admin-bots"
if [ -f "$NGINX_CONF" ]; then
    log "Updating nginx timeouts..."
    if ! grep -q "proxy_read_timeout" "$NGINX_CONF"; then
        sed -i '/proxy_pass/a\        proxy_connect_timeout 30s;\n        proxy_send_timeout 120s;\n        proxy_read_timeout 120s;' "$NGINX_CONF"
    fi
    nginx -t && systemctl reload nginx
fi

# Reload and restart
log "Restarting services..."
systemctl daemon-reload
systemctl start admin_panel

sleep 3

if systemctl is-active --quiet admin_panel; then
    log "✅ Admin panel is running"
    
    # Test connection
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health 2>/dev/null | grep -q "200\|404"; then
        log "✅ Panel responds to requests"
    else
        warn "Panel may need more time to start"
    fi
else
    err "Admin panel failed to start. Check: sudo journalctl -u admin_panel -f"
fi

log "=== Fix Complete ==="
echo ""
echo "If issues persist:"
echo "  1. Check logs: sudo journalctl -u admin_panel -f"
echo "  2. Run diagnostics: sudo bash $PROJECT_DIR/scripts/diagnose.sh"
