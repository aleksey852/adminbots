#!/bin/bash
# Admin Bots Platform - Deploy Script v4.0 (Zero-Config)
# Usage: sudo bash scripts/deploy.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[!]${NC} $1"; exit 1; }

# Check root
[[ $EUID -ne 0 ]] && err "Run as root: sudo bash scripts/deploy.sh"

PROJECT_DIR="/opt/admin-bots-platform"
SERVICE_USER="adminbots"
BACKUP_DIR="/var/backups/admin-bots-platform"

log "=== Admin Bots Platform Deploy v4.0 (Zero-Config) ==="

# Create backup directory
mkdir -p "$BACKUP_DIR"

# 1. System packages
log "Installing system packages..."
apt-get update
apt-get install -y python3 python3-pip python3-venv postgresql postgresql-contrib redis-server nginx certbot python3-certbot-nginx logrotate cron ufw

# 1.1 Firewall Setup
log "Configuring Firewall..."
ufw allow 22/tcp  # SSH
ufw allow 80/tcp  # HTTP
ufw allow 443/tcp # HTTPS
ufw --force enable


# 2. Server Optimization
log "Optimizing server..."
RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
if [ "$RAM_GB" -eq 0 ]; then RAM_GB=1; fi

# Swap
if [ ! -f /swapfile ]; then
    SWAP_SIZE=$((RAM_GB * 2))
    [ $SWAP_SIZE -gt 4 ] && SWAP_SIZE=4
    fallocate -l ${SWAP_SIZE}G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=$((SWAP_SIZE * 1024))
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q "/swapfile" /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Sysctl
cat > /etc/sysctl.d/99-admin-bots.conf << EOF
vm.swappiness=10
vm.overcommit_memory=1
net.core.somaxconn=4096
net.ipv4.tcp_max_syn_backlog=4096
EOF
sysctl -p /etc/sysctl.d/99-admin-bots.conf

# 3. Create service user
    useradd -m -s /bin/bash "$SERVICE_USER"
    usermod -aG systemd-journal "$SERVICE_USER"
fi

# 3.1 Configure Sudoers for Script Execution
log "Configuring sudoers..."
echo "$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/bash $PROJECT_DIR/scripts/setup_domain.sh *" > /etc/sudoers.d/adminbots
chmod 0440 /etc/sudoers.d/adminbots


# 4. Copy project
log "Setting up project..."
mkdir -p "$PROJECT_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -f "$SOURCE_DIR/main.py" ]]; then
    # Copy project files (include .git for updates)
    rsync -a --exclude 'venv' --exclude '__pycache__' --exclude '.env' "$SOURCE_DIR/" "$PROJECT_DIR/"
fi

# Ensure .git permissions
if [ -d "$PROJECT_DIR/.git" ]; then
    chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR/.git"


# Git safe dir
if [ -d "$PROJECT_DIR" ]; then
    git config --global --add safe.directory "$PROJECT_DIR"
fi

# 5. Generate Credentials (Zero-Config Magic)
DB_PASS=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
ADMIN_PASS=$(openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | head -c 12)
SECRET_KEY=$(openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 48)

# Detect Public IP
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')
DOMAIN="" # Optional, can be set later in nginx

# 6. Database Setup
log "Setting up Database..."
sudo -u postgres psql -c "CREATE USER $SERVICE_USER WITH PASSWORD '$DB_PASS' CREATEDB;" 2>/dev/null || \
sudo -u postgres psql -c "ALTER USER $SERVICE_USER WITH PASSWORD '$DB_PASS' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE admin_bots OWNER $SERVICE_USER;" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE admin_bots TO $SERVICE_USER;"

# 7. Create .env (Defaults)
log "Creating .env..."
cat > "$PROJECT_DIR/.env" << EOF
# System config
DATABASE_URL=postgresql://$SERVICE_USER:$DB_PASS@127.0.0.1:5432/admin_bots
REDIS_URL=redis://localhost:6379/0
ADMIN_PANEL_USER=admin
ADMIN_PANEL_PASSWORD=$ADMIN_PASS
ADMIN_SECRET_KEY=$SECRET_KEY

# Bot Defaults (Fill via Admin Panel later if needed, but these are legacy env vars)
BOT_TOKEN=
ADMIN_IDS=
PROVERKA_CHEKA_TOKEN=
PROMO_NAME=Admin Bots
TIMEZONE=Europe/Moscow
LOG_LEVEL=INFO
METRICS_ENABLED=true
EOF
chmod 600 "$PROJECT_DIR/.env"

# 8. Python Env
log "Installing dependencies..."
python3 -m venv "$PROJECT_DIR/venv"
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR"

# 9. Systemd Services
log "Installing services..."
# Admin Bots (Backend)
cat > /etc/systemd/system/admin_bots.service << EOF
[Unit]
Description=Admin Bots Telegram Core
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/venv/bin/python main.py
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

# Admin Panel (Web)
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
# Listen on 127.0.0.1 by default, Nginx handles external access
ExecStart=$PROJECT_DIR/venv/bin/uvicorn admin_panel.app:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable admin_bots admin_panel
systemctl restart admin_bots admin_panel

# 10. Nginx (Auto-IP)
log "Configuring Nginx..."
# Default catch-all config for IP access
cat > /etc/nginx/sites-available/admin-bots << EOF
server {
    listen 80 default_server;
    server_name _;
    
    # Принимаем большие файлы (импорт промокодов)
    client_max_body_size 1G;
    client_body_timeout 600s;
    client_header_timeout 600s;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 600;
        proxy_send_timeout 600;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_connect_timeout 60;
    }
}
EOF
ln -sf /etc/nginx/sites-available/admin-bots /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# 11. Cron & Logrotate
# ... (Standard setup same as before) ...
cat > /etc/logrotate.d/admin-bots << EOF
/var/log/admin-bots*.log {
    daily
    missingok
    rotate 7
    compress
    create 0640 root root
}
EOF

# 12. Save Credentials
CREDS_FILE="/root/admin_bots_credentials.txt"
cat > "$CREDS_FILE" << EOF
===========================================
  🚀 Admin Bots Platform Installed!
===========================================

🌐 ADMIN PANEL
   URL:      http://$PUBLIC_IP
   Login:    admin
   Password: $ADMIN_PASS

🗄️ DATABASE (PostgreSQL)
   Host:     127.0.0.1:5432
   Database: admin_bots
   User:     $SERVICE_USER
   Password: $DB_PASS

🔧 Next Steps:
   1. Open Admin Panel
   2. Go to 'Add Bot' to connect your first bot
   3. Configure settings in UI

===========================================
EOF
chmod 600 "$CREDS_FILE"

echo ""
log "✅ Installation Complete!"
echo ""
echo -e "${CYAN}===========================================${NC}"
echo -e "${CYAN}   ADMIN PANEL ACCESS                      ${NC}"
echo -e "${CYAN}===========================================${NC}"
echo -e "URL:      http://$PUBLIC_IP"
echo -e "Login:    admin"
echo -e "Password: ${YELLOW}$ADMIN_PASS${NC}"
echo ""
echo -e "Saved to: $CREDS_FILE"
echo ""
