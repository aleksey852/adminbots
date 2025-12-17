#!/bin/bash
# Admin Bots Platform - Diagnostics Script
# Usage: sudo bash scripts/diagnose.sh

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_DIR="/opt/admin-bots-platform"

echo -e "${CYAN}=== Admin Bots Platform Diagnostics ===${NC}"
echo ""

# Services
echo -e "${CYAN}[Services]${NC}"
echo -n "Bot Manager: "
systemctl is-active admin_bots && echo -e "${GREEN}✓ Running${NC}" || echo -e "${RED}✗ Not running${NC}"
echo -n "Admin Panel: "
systemctl is-active admin_panel && echo -e "${GREEN}✓ Running${NC}" || echo -e "${RED}✗ Not running${NC}"
echo -n "PostgreSQL: "
systemctl is-active postgresql && echo -e "${GREEN}✓ Running${NC}" || echo -e "${RED}✗ Not running${NC}"
echo -n "Redis: "
systemctl is-active redis-server && echo -e "${GREEN}✓ Running${NC}" || echo -e "${RED}✗ Not running${NC}"
echo -n "Nginx: "
systemctl is-active nginx && echo -e "${GREEN}✓ Running${NC}" || echo -e "${RED}✗ Not running${NC}"

# Port check
echo ""
echo -e "${CYAN}[Ports]${NC}"
echo -n "8000 (Admin Panel): "
ss -tlnp | grep -q ":8000" && echo -e "${GREEN}✓ Listening${NC}" || echo -e "${RED}✗ Not listening${NC}"
echo -n "5432 (PostgreSQL): "
ss -tlnp | grep -q ":5432" && echo -e "${GREEN}✓ Listening${NC}" || echo -e "${RED}✗ Not listening${NC}"
echo -n "6379 (Redis): "
ss -tlnp | grep -q ":6379" && echo -e "${GREEN}✓ Listening${NC}" || echo -e "${RED}✗ Not listening${NC}"

# Memory
echo ""
echo -e "${CYAN}[Memory]${NC}"
free -h | head -2

# Disk
echo ""
echo -e "${CYAN}[Disk]${NC}"
df -h / | tail -1

# Recent logs
echo ""
echo -e "${CYAN}[Recent Bot Errors]${NC}"
journalctl -u admin_bots --no-pager -n 5 --priority=err 2>/dev/null || echo "No errors"

echo ""
echo -e "${CYAN}[Recent Panel Errors]${NC}"
journalctl -u admin_panel --no-pager -n 5 --priority=err 2>/dev/null || echo "No errors"

echo ""
echo -e "${CYAN}=== Diagnostics Complete ===${NC}"
echo ""
echo "For live logs:"
echo "  sudo journalctl -u admin_bots -f"
echo "  sudo journalctl -u admin_panel -f"
