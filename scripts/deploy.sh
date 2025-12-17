#!/bin/bash
# Admin Bots Platform - Deploy Script v3.1 (Multi-Bot Optimized)
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

# Check OS (Debian/Ubuntu only)
if ! command -v apt-get &> /dev/null; then
    err "This script requires apt-get (Debian/Ubuntu). Your OS is not supported."
fi

PROJECT_DIR="/opt/admin-bots-platform"
SERVICE_USER="buster"
BACKUP_DIR="/var/backups/admin-bots-platform"

log "=== Admin Bots Platform Deploy v3.1 (Multi-Bot) ==="

# 1. System packages
log "Installing system packages..."
apt-get update
apt-get install -y python3 python3-pip python3-venv postgresql postgresql-contrib redis-server nginx certbot python3-certbot-nginx logrotate cron

# 2. Server Optimization (auto-detect RAM)
log "Optimizing server..."
RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
if [ "$RAM_GB" -eq 0 ]; then
    RAM_GB=1
fi
log "Detected RAM: ${RAM_GB}GB"

# 2.1 Swap Configuration
if [ ! -f /swapfile ]; then
    SWAP_SIZE=$((RAM_GB * 2))
    [ $SWAP_SIZE -gt 4 ] && SWAP_SIZE=4
    log "Creating ${SWAP_SIZE}GB Swap..."
    fallocate -l ${SWAP_SIZE}G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=$((SWAP_SIZE * 1024))
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q "/swapfile" /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# 2.2 Sysctl tuning (multi-bot optimized)
log "Tuning sysctl for multi-bot..."
cat > /etc/sysctl.d/99-admin-bots-optimization.conf << EOF
# Prefer RAM over swap
vm.swappiness=10

# Allow Redis memory overcommit
vm.overcommit_memory=1

# Multi-bot: increase connection backlog
net.core.somaxconn=4096
net.core.netdev_max_backlog=4096

# TCP optimization for many connections
net.ipv4.tcp_max_syn_backlog=4096
net.ipv4.ip_local_port_range=1024 65535
net.ipv4.tcp_tw_reuse=1

# File descriptors (kernel level)
fs.file-max=100000
EOF
sysctl -p /etc/sysctl.d/99-admin-bots-optimization.conf

# 2.3 Ulimit for service user (multi-bot: many file descriptors)
log "Setting ulimits for multi-bot..."
cat > /etc/security/limits.d/99-admin-bots.conf << EOF
# Admin Bots Platform - increased limits for multi-bot
$SERVICE_USER soft nofile 65535
$SERVICE_USER hard nofile 65535
$SERVICE_USER soft nproc 4096
$SERVICE_USER hard nproc 4096
EOF

# 2.4 PostgreSQL Tuning
log "Tuning PostgreSQL..."
PG_CONF=$(find /etc/postgresql -name postgresql.conf | head -n 1)
if [ -n "$PG_CONF" ]; then
    SHARED_BUFFERS=$((RAM_GB * 256))
    [ $SHARED_BUFFERS -gt 2048 ] && SHARED_BUFFERS=2048
    [ $SHARED_BUFFERS -lt 128 ] && SHARED_BUFFERS=128
    
    MAX_CONN=$((50 + RAM_GB * 20))
    [ $MAX_CONN -gt 200 ] && MAX_CONN=200
    
    sed -i "s/#shared_buffers = 128MB/shared_buffers = ${SHARED_BUFFERS}MB/" "$PG_CONF"
    sed -i "s/shared_buffers = .*/shared_buffers = ${SHARED_BUFFERS}MB/" "$PG_CONF"
    sed -i "s/#max_connections = 100/max_connections = $MAX_CONN/" "$PG_CONF"
    sed -i "s/max_connections = .*/max_connections = $MAX_CONN/" "$PG_CONF"
    
    log "PostgreSQL: shared_buffers=${SHARED_BUFFERS}MB, max_connections=$MAX_CONN"
    systemctl restart postgresql
fi

# 2.5 Redis Tuning
log "Tuning Redis..."
REDIS_CONF="/etc/redis/redis.conf"
if [ -f "$REDIS_CONF" ]; then
    REDIS_MEM=$((RAM_GB * 128))
    [ $REDIS_MEM -lt 256 ] && REDIS_MEM=256
    [ $REDIS_MEM -gt 1024 ] && REDIS_MEM=1024
    
    sed -i "s/# maxmemory <bytes>/maxmemory ${REDIS_MEM}mb/" "$REDIS_CONF"
    sed -i "s/^maxmemory .*/maxmemory ${REDIS_MEM}mb/" "$REDIS_CONF"
    sed -i "s/# maxmemory-policy noeviction/maxmemory-policy allkeys-lru/" "$REDIS_CONF"
    sed -i "s/^maxmemory-policy .*/maxmemory-policy allkeys-lru/" "$REDIS_CONF"
    
    log "Redis: maxmemory=${REDIS_MEM}MB"
    systemctl restart redis-server
fi

# 3. Create service user
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$SERVICE_USER"
    log "Created user: $SERVICE_USER"
fi

# 4. Copy project
log "Setting up project..."
mkdir -p "$PROJECT_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -f "$SOURCE_DIR/main.py" ]]; then
    cp -r "$SOURCE_DIR/." "$PROJECT_DIR/"
fi

# Configure git safe directory
if [ -d "$PROJECT_DIR" ]; then
    git config --global --add safe.directory "$PROJECT_DIR"
    
    if [ ! -d "$PROJECT_DIR/.git" ]; then
        log "Initializing git repository..."
        cd "$PROJECT_DIR"
        git init
        git remote add origin https://github.com/aleksey852/adminbots.git
        git fetch
        git reset --hard origin/main
        cd - > /dev/null
    fi
fi

# 5. Get config from user
echo ""
read -p "Bot Token: " BOT_TOKEN
read -p "Admin Telegram IDs (comma-separated): " ADMIN_IDS
read -p "ProverkaCheka Token: " API_TOKEN
read -p "Domain (or press Enter for IP only): " DOMAIN
read -p "Platform Name [Admin Bots]: " PROMO_NAME
PROMO_NAME=${PROMO_NAME:-Admin Bots}

# Generate passwords
DB_PASS=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
ADMIN_PASS=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
SECRET_KEY=$(openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 48)

# Calculate promo dates (GNU date compatible)
PROMO_START=$(date +%Y-%m-%d)
PROMO_END=$(date -d "+90 days" +%Y-%m-%d 2>/dev/null || date -v+90d +%Y-%m-%d 2>/dev/null || echo "2026-03-15")

# 6. Setup PostgreSQL
log "Setting up PostgreSQL..."
cd /tmp
sudo -u postgres psql -c "CREATE USER $SERVICE_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || true
sudo -u postgres psql -c "ALTER USER $SERVICE_USER WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -c "CREATE DATABASE admin_bots OWNER $SERVICE_USER;" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE admin_bots TO $SERVICE_USER;"
cd - > /dev/null

# 7. Create .env
log "Creating .env..."
cat > "$PROJECT_DIR/.env" << EOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_IDS=$ADMIN_IDS
DATABASE_URL=postgresql://$SERVICE_USER:$DB_PASS@127.0.0.1:5432/admin_bots
REDIS_URL=redis://localhost:6379/0
PROVERKA_CHEKA_TOKEN=$API_TOKEN
PROMO_NAME=$PROMO_NAME
PROMO_START_DATE=$PROMO_START
PROMO_END_DATE=$PROMO_END
PROMO_PRIZES=iPhone 15,AirPods,Сертификаты 5000₽
TARGET_KEYWORDS=чипсы,admin,bots
SUPPORT_EMAIL=support@example.com
SUPPORT_TELEGRAM=@support
ADMIN_PANEL_USER=admin
ADMIN_PANEL_PASSWORD=$ADMIN_PASS
ADMIN_SECRET_KEY=$SECRET_KEY
TIMEZONE=Europe/Moscow
LOG_LEVEL=INFO
SCHEDULER_INTERVAL=30
MESSAGE_DELAY_SECONDS=0.05
BROADCAST_BATCH_SIZE=20
DB_POOL_MIN=2
DB_POOL_MAX=10
STATS_CACHE_TTL=60
RECEIPTS_RATE_LIMIT=50
RECEIPTS_DAILY_LIMIT=200
METRICS_ENABLED=true
METRICS_PORT=9090
EOF
chmod 600 "$PROJECT_DIR/.env"

# 8. Python venv
log "Setting up Python environment..."
python3 -m venv "$PROJECT_DIR/venv"
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 9. Set ownership
chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR"

# 10. Create systemd services (multi-bot optimized)
log "Creating systemd services..."

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
StandardOutput=journal
StandardError=journal
# Multi-bot: increased limits
LimitNOFILE=65535
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
EOF

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
# Multi-bot: 4 workers for handling multiple bot contexts
ExecStart=$PROJECT_DIR/venv/bin/uvicorn admin_panel.app:app --host 127.0.0.1 --port 8000 --workers 4 --timeout-keep-alive 120
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
LimitNOFILE=65535
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable admin_bots admin_panel
systemctl restart admin_bots admin_panel

# 11. Setup Nginx (if domain provided)
if [[ -n "$DOMAIN" ]]; then
    log "Setting up Nginx for $DOMAIN..."
    cat > /etc/nginx/sites-available/admin-bots << EOF
server {
    listen 80;
    server_name $DOMAIN;
    
    client_max_body_size 10M;
    
    # Timeouts - prevent 502 on slow operations
    proxy_connect_timeout 30s;
    proxy_send_timeout 120s;
    proxy_read_timeout 120s;
    send_timeout 120s;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
    ln -sf /etc/nginx/sites-available/admin-bots /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl reload nginx
    
    log "Getting SSL certificate..."
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "admin@$DOMAIN" || true
fi

# 12. Setup automatic backups (cron)
log "Setting up automatic backups..."
mkdir -p "$BACKUP_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$BACKUP_DIR"

# Cron job for daily backups at 3 AM
CRON_JOB="0 3 * * * /bin/bash $PROJECT_DIR/scripts/backup.sh >> /var/log/admin-bots-backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "admin-bots"; echo "$CRON_JOB") | crontab -
log "✅ Daily backup scheduled (3:00 AM)"

# 13. Setup logrotate
log "Setting up logrotate..."
cat > /etc/logrotate.d/admin-bots << EOF
/var/log/admin-bots*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 root root
}
EOF

# 14. Save credentials (clean, no duplicates)
CREDS_FILE="/root/admin_bots_credentials.txt"
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')
cat > "$CREDS_FILE" << EOF
===========================================
  Admin Bots Platform - Credentials
  Generated: $(date)
===========================================

🌐 ADMIN PANEL
   URL: $([ -n "$DOMAIN" ] && echo "https://$DOMAIN" || echo "http://$PUBLIC_IP:8000")
   Login: admin
   Password: $ADMIN_PASS

🗄️ DATABASE
   Name: admin_bots
   User: $SERVICE_USER
   Password: $DB_PASS
   URL: postgresql://$SERVICE_USER:****@127.0.0.1:5432/admin_bots

🔐 SECRET KEY
   $SECRET_KEY

📂 PATHS
   Project: $PROJECT_DIR
   Backups: $BACKUP_DIR (14-day retention, daily at 3 AM)

⚙️ COMMANDS
   Bot Status:    sudo systemctl status admin_bots
   Bot Logs:      sudo journalctl -u admin_bots -f
   Bot Restart:   sudo systemctl restart admin_bots

   Panel Status:  sudo systemctl status admin_panel
   Panel Logs:    sudo journalctl -u admin_panel -f
   Panel Restart: sudo systemctl restart admin_panel

   Manual Backup: sudo bash $PROJECT_DIR/scripts/backup.sh
   Update:        sudo bash $PROJECT_DIR/scripts/update.sh
   Optimize:      sudo bash $PROJECT_DIR/scripts/optimize_server.sh

   Database:      sudo -u postgres psql admin_bots
EOF
chmod 600 "$CREDS_FILE"

echo ""
log "=== Installation Complete! ==="
echo ""
log "✅ Bot is running"
log "✅ Admin panel is running"
log "✅ Daily backups scheduled (3:00 AM)"
log "✅ Logrotate configured"
log "✅ Server optimized for multi-bot"
echo ""
log "Credentials saved to: $CREDS_FILE"
log "View: cat $CREDS_FILE"
