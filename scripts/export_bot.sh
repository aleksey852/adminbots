#!/bin/bash
# Admin Bots Platform - Bot Export Script v1.0
# Usage: bash scripts/export_bot.sh <bot_id>

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[!]${NC} $1"; exit 1; }

# 1. Check Arguments
BOT_ID=$1
[[ -z "$BOT_ID" ]] && err "Usage: bash scripts/export_bot.sh <bot_id>"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPORT_DIR="$PROJECT_DIR/exports"
mkdir -p "$EXPORT_DIR"

# 2. Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
else
    err ".env file not found in $PROJECT_DIR"
fi

# 3. Get Bot Info from Panel DB
log "Fetching bot info for ID: $BOT_ID..."
BOT_INFO=$(psql "$DATABASE_URL" -t -A -c "SELECT name, database_url FROM bot_registry WHERE id = $BOT_ID;")
[[ -z "$BOT_INFO" ]] && err "Bot with ID $BOT_ID not found in registry."

BOT_NAME=$(echo "$BOT_INFO" | cut -d'|' -f1)
BOT_DB_URL=$(echo "$BOT_INFO" | cut -d'|' -f2)

# Extract DB name from URL
# postgres://user:pass@host:port/dbname
BOT_DB_NAME=$(echo "$BOT_DB_URL" | psql -t -A -c "SELECT pg_catalog.current_database();" "$BOT_DB_URL" 2>/dev/null || echo "$BOT_DB_URL" | sed 's/.*\///')

log "Exporting Bot: $BOT_NAME (DB: $BOT_DB_NAME)"

# 4. Create Temp Workspace
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

WORK_DIR="$TMP_DIR/bot_export_$BOT_ID"
mkdir -p "$WORK_DIR/code"
mkdir -p "$WORK_DIR/database"

# 5. Backup Database
log "Dumping database $BOT_DB_NAME..."
pg_dump "$BOT_DB_URL" > "$WORK_DIR/database/dump.sql"

# 6. Copy Project Code
log "Copying project code..."
rsync -a \
    --exclude 'venv' \
    --exclude '.git' \
    --exclude '.env' \
    --exclude '__pycache__' \
    --exclude 'exports' \
    --exclude 'admin_panel/uploads' \
    --exclude '*.log' \
    --exclude '.DS_Store' \
    "$PROJECT_DIR/" "$WORK_DIR/code/"

# Create a clean .env template for the client
cat > "$WORK_DIR/code/.env.example" << EOF
DATABASE_URL=postgresql://user:pass@localhost:5432/$BOT_DB_NAME
REDIS_URL=redis://localhost:6379/0
ADMIN_PANEL_USER=admin
ADMIN_PANEL_PASSWORD=change_me
ADMIN_SECRET_KEY=$(openssl rand -base64 32)
EOF

# 7. Package everything
log "Creating archive..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE_NAME="bot_export_${BOT_ID}_${TIMESTAMP}.zip"
cd "$TMP_DIR"
zip -r "$EXPORT_DIR/$ARCHIVE_NAME" "bot_export_$BOT_ID" > /dev/null

log "✅ Export Complete!"
echo -e "${CYAN}===========================================${NC}"
echo -e "Archive: ${YELLOW}$EXPORT_DIR/$ARCHIVE_NAME${NC}"
echo -e "${CYAN}===========================================${NC}"
