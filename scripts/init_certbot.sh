#!/usr/bin/env bash
set -e

DOMAIN=$1
EMAIL=$2

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Usage: ./scripts/init_certbot.sh <domain-name> <email-address>"
    echo "Example: ./scripts/init_certbot.sh example.com admin@example.com"
    exit 1
fi

echo "=== Initializing Let's Encrypt Certificate for $DOMAIN ==="

# Execute Certbot webroot challenge using active Nginx webroot
docker compose exec certbot certbot certonly \
    --webroot \
    -w /var/www/certbot \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --non-interactive

echo "=== Certificate issued successfully! Reloading Nginx ==="
docker compose exec nginx nginx -s reload

echo "=== Testing Renewal Dry-Run ==="
docker compose exec certbot certbot renew --dry-run

echo "=== Let's Encrypt SSL setup completed for $DOMAIN ==="
