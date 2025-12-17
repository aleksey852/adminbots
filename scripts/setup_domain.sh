#!/bin/bash
# Domain Setup Script for Admin Bots Platform
# Usage: sudo bash scripts/setup_domain.sh <domain> [email]
# Example: sudo bash scripts/setup_domain.sh admin.example.com admin@example.com

set -e

DOMAIN=$1
EMAIL=${2:-"admin@$DOMAIN"}

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# Check root
[[ $EUID -ne 0 ]] && err "Run as root: sudo bash scripts/setup_domain.sh <domain>"

# Check domain argument
if [ -z "$DOMAIN" ]; then
    err "Usage: sudo bash scripts/setup_domain.sh <domain> [email]"
fi

# Validate domain format (basic)
if ! echo "$DOMAIN" | grep -qE '^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$'; then
    err "Invalid domain format: $DOMAIN"
fi

log "=== Setting up domain: $DOMAIN ==="

# 1. Create nginx config for domain
NGINX_CONF="/etc/nginx/sites-available/admin-bots-$DOMAIN"
log "Creating nginx config..."

cat > "$NGINX_CONF" << EOF
server {
    listen 80;
    server_name $DOMAIN;
    
    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    # Proxy to admin panel
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
        
        # Large file uploads (promo codes)
        client_max_body_size 1G;
        client_body_timeout 600s;
    }
}
EOF

# Enable site
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/

# 2. Test nginx config
log "Testing nginx config..."
if ! nginx -t; then
    rm -f "/etc/nginx/sites-enabled/admin-bots-$DOMAIN"
    err "Nginx config test failed!"
fi

# Reload nginx
systemctl reload nginx
log "✅ Nginx configured for $DOMAIN"

# 3. Check if domain resolves to this server
log "Checking DNS..."
SERVER_IP=$(curl -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')
DOMAIN_IP=$(dig +short "$DOMAIN" | head -1)

if [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
    warn "⚠️ Domain $DOMAIN does not resolve to this server ($SERVER_IP)"
    warn "   Domain resolves to: $DOMAIN_IP"
    warn "   Please update your DNS A record to point to $SERVER_IP"
    warn "   SSL certificate will fail until DNS is configured correctly"
    echo ""
    log "Nginx is configured. Run this script again after DNS propagation to get SSL."
    exit 0
fi

log "✅ DNS verified: $DOMAIN -> $SERVER_IP"

# 4. Get SSL certificate
log "Obtaining SSL certificate..."
if command -v certbot &> /dev/null; then
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$EMAIL" --redirect
    
    if [ $? -eq 0 ]; then
        log "✅ SSL certificate obtained!"
        log "✅ HTTPS redirect enabled"
    else
        warn "SSL certificate failed. Check certbot logs."
    fi
else
    warn "Certbot not installed. Install with: apt install certbot python3-certbot-nginx"
fi

# 5. Save domain config
DOMAIN_FILE="/opt/admin-bots-platform/.domain"
echo "$DOMAIN" > "$DOMAIN_FILE"
chmod 600 "$DOMAIN_FILE"

echo ""
log "=== Domain Setup Complete ==="
log "Domain: https://$DOMAIN"
echo ""
