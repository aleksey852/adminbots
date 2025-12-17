#!/bin/bash
# Database Backup Script for Admin Bots Platform
# Usage: sudo bash scripts/backup.sh

set -e

BACKUP_DIR="/var/backups/admin-bots-platform"
PROJECT_DIR="/opt/admin-bots-platform"
RETENTION_DAYS=14
MIN_FREE_SPACE_MB=500

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# Allow overriding BACKUP_DIR from first argument
if [ -n "$1" ]; then
    BACKUP_DIR="$1"
fi

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Check if backup directory is writable
if [ ! -w "$BACKUP_DIR" ]; then
    err "Backup directory $BACKUP_DIR is not writable!"
fi

# Check free disk space
FREE_SPACE_MB=$(df -m "$BACKUP_DIR" | tail -1 | awk '{print $4}')

log "=== Database Backup Started ==="
log "Backup directory: $BACKUP_DIR"
log "Free space: ${FREE_SPACE_MB}MB"

if [ "$FREE_SPACE_MB" -lt "$MIN_FREE_SPACE_MB" ]; then
    err "Insufficient disk space! Free: ${FREE_SPACE_MB}MB, Required: ${MIN_FREE_SPACE_MB}MB"
fi

# Timestamp for backup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/backup_${TIMESTAMP}.sql"

# Get database credentials from .env
if [ -f "$PROJECT_DIR/.env" ]; then
    DATABASE_URL=$(grep "^DATABASE_URL=" "$PROJECT_DIR/.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
else
    warn ".env file not found, using defaults"
    DATABASE_URL="postgresql://adminbots:password@localhost:5432/admin_bots"
fi

# Extract DB connection details from DATABASE_URL
if [ -n "$DATABASE_URL" ]; then
    PROTO_REMOVED="${DATABASE_URL#*://}"
    USER_PASS="${PROTO_REMOVED%@*}"
    HOST_DB="${PROTO_REMOVED#*@}"
    
    DB_USER="${USER_PASS%:*}"
    PGPASSWORD="${USER_PASS#*:}"
    
    DB_HOST_PORT="${HOST_DB%/*}"
    DB_NAME="${HOST_DB#*/}"
    DB_NAME="${DB_NAME%%\?*}"
    
    DB_HOST="${DB_HOST_PORT%:*}"
    DB_PORT="${DB_HOST_PORT#*:}"
    
    if [ "$DB_HOST" = "$DB_PORT" ]; then
        DB_PORT="5432"
    fi
fi

DB_NAME=${DB_NAME:-admin_bots}
DB_HOST=${DB_HOST:-localhost}
DB_PORT=${DB_PORT:-5432}

log "Database: $DB_NAME @ $DB_HOST:$DB_PORT"

# Perform backup
export PGPASSWORD
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    --format=plain \
    --no-owner \
    --no-acl \
    > "$BACKUP_FILE" 2>&1 || err "Backup failed!"

# Compress backup
gzip "$BACKUP_FILE"
BACKUP_FILE="${BACKUP_FILE}.gz"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "✅ Backup created: $BACKUP_FILE"
log "   Size: $BACKUP_SIZE"

# Backup .env file
ENV_BACKUP="$BACKUP_DIR/env_${TIMESTAMP}.txt"
if [ -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env" "$ENV_BACKUP"
    chmod 600 "$ENV_BACKUP"
    log "✅ .env backed up"
fi

# Clean old backups
log "Cleaning backups older than ${RETENTION_DAYS} days..."
DELETED_COUNT=0

for file in $(find "$BACKUP_DIR" -name "backup_*.sql.gz" -mtime +${RETENTION_DAYS}); do
    rm -f "$file"
    DELETED_COUNT=$((DELETED_COUNT + 1))
done

for file in $(find "$BACKUP_DIR" -name "env_*.txt" -mtime +${RETENTION_DAYS}); do
    rm -f "$file"
    DELETED_COUNT=$((DELETED_COUNT + 1))
done

if [ $DELETED_COUNT -gt 0 ]; then
    log "✅ Deleted $DELETED_COUNT old backup(s)"
fi

BACKUP_COUNT=$(find "$BACKUP_DIR" -name "backup_*.sql.gz" | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)

echo ""
log "=== Backup Complete ==="
log "Total backups: $BACKUP_COUNT (${RETENTION_DAYS}-day retention)"
log "Total size: $TOTAL_SIZE"
echo ""
log "To restore from this backup:"
log "  sudo systemctl stop admin_bots admin_panel"
log "  gunzip -c $BACKUP_FILE | sudo -u postgres psql $DB_NAME"
log "  sudo systemctl start admin_bots admin_panel"
