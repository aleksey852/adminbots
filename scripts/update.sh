#!/bin/bash
# Universal Update Script for Admin Bots Platform
# Usage: sudo bash scripts/update.sh

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

# Check root
if [[ $EUID -ne 0 ]]; then
   err "This script must be run as root: sudo bash scripts/update.sh"
fi

echo -e "
╔════════════════════════════════════════╗
║    🚀 Admin Bots Platform Updater      ║
╚════════════════════════════════════════╝
"

# 1. Update Code
log "Starting code update..."

# Ensure we are working with safe directory for git
if [ -d "$PROJECT_DIR" ]; then
    git config --global --add safe.directory "$PROJECT_DIR"
fi

if [ -d "$PROJECT_DIR/.git" ]; then
    log "Detected Git repository in $PROJECT_DIR"
    cd "$PROJECT_DIR"
    
    # Check for local changes
    if [[ -n $(git status -s) ]]; then
        warn "Local changes detected. Stashing them..."
        git stash || warn "Failed to stash changes"
    fi

    log "Pulling latest changes..."
    git pull origin main || git pull origin master || err "Failed to pull from git"
    
    # Get last commit hash
    LAST_COMMIT=$(git rev-parse --short HEAD)
    log "Updated to commit: $LAST_COMMIT"
    
elif [ -d "$(pwd)/.git" ]; then
    # If we are running from a git repo but PROJECT_DIR is different (rsync mode)
    SOURCE_DIR="$(pwd)"
    if [ "$SOURCE_DIR" != "$PROJECT_DIR" ]; then
        log "Syncing files from $SOURCE_DIR to $PROJECT_DIR..."
        rsync -av --exclude 'venv' --exclude '.git' --exclude '__pycache__' --exclude '.env' "$SOURCE_DIR/" "$PROJECT_DIR/"
    fi
else
    warn "No git repository found in $PROJECT_DIR or current directory."
    warn "Assuming manual file upload. Proceeding with dependency updates..."
fi

# 2. Permissions
log "Fixing permissions..."
chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR"
chmod +x "$PROJECT_DIR/scripts/"*.sh

# 3. Dependencies (skip if requirements.txt hasn't changed)
log "Checking Python dependencies..."
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    REQ_HASH=$(md5sum "$PROJECT_DIR/requirements.txt" | cut -d' ' -f1)
    OLD_HASH=$(cat "$PROJECT_DIR/.req_hash" 2>/dev/null || echo "")
    
    if [ "$REQ_HASH" != "$OLD_HASH" ]; then
        log "Updating Python dependencies..."
        sudo -u "$SERVICE_USER" "$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" | grep -v "Requirement already satisfied" || true
        echo "$REQ_HASH" > "$PROJECT_DIR/.req_hash"
    else
        log "Dependencies unchanged, skipping pip install"
    fi
else
    warn "requirements.txt not found!"
fi

# 4. Migrations (Optional)
# Schema migration is auto-handled by bot_db.py on startup
# This section is for data migrations if any
if [ -f "$PROJECT_DIR/scripts/setup/migrate.py" ]; then
    log "Checking for data migrations..."
    cd "$PROJECT_DIR"
    sudo -u "$SERVICE_USER" "$PROJECT_DIR/venv/bin/python" scripts/setup/migrate.py || true
fi

# 5. Restart Services
log "Restarting system services..."
systemctl restart admin_bots
systemctl restart admin_panel

# 6. Verify
sleep 2
BOT_STATUS=$(systemctl is-active admin_bots)
PANEL_STATUS=$(systemctl is-active admin_panel)

if [ "$BOT_STATUS" == "active" ]; then
    log "✅ Bot Service: Active"
else
    err "❌ Bot Service: $BOT_STATUS (Check logs: sudo journalctl -u admin_bots -n 50)"
fi

if [ "$PANEL_STATUS" == "active" ]; then
    log "✅ Admin Panel: Active"
else
    err "❌ Admin Panel: $PANEL_STATUS (Check logs: sudo journalctl -u admin_panel -n 50)"
fi

echo ""
log "Update finished successfully! 🚀"
