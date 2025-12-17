#!/bin/bash
# Admin Bots Platform - Live Debug
# Usage: sudo bash scripts/live_debug.sh

echo "=== Live Debug ==="
echo ""

echo "[1] Checking code versions..."
echo -n "Advisory locks: "
grep -q "pg_try_advisory_lock" /opt/admin-bots-platform/database/db.py && echo "YES ✓" || echo "NO ✗ (old version!)"
echo -n "Slow request logging: "
grep -q "log_slow_requests" /opt/admin-bots-platform/admin_panel/app.py && echo "YES ✓" || echo "NO ✗ (old version!)"

echo ""
echo "[2] Starting live log monitoring..."
echo "Press Ctrl+C to stop"
echo ""

# Show admin panel logs
journalctl -u admin_panel -f --no-pager
