param (
    [Parameter(Mandatory=$true)]
    [string]$Domain,

    [Parameter(Mandatory=$true)]
    [string]$Email
)

$ErrorActionPreference = "Stop"

Write-Host "=== Initializing Let's Encrypt Certificate for $Domain ===" -ForegroundColor Green

docker compose exec certbot sh -c '
set -e
domain="$1"
marker="/etc/letsencrypt/.medicore-placeholder-${domain}"
if [ -f "$marker" ]; then
    rm -rf "/etc/letsencrypt/live/${domain}" "/etc/letsencrypt/archive/${domain}" "/etc/letsencrypt/renewal/${domain}.conf" "$marker"
fi
' sh $Domain

docker compose exec certbot certbot certonly `
    --webroot `
    -w /var/www/certbot `
    -d $Domain `
    --email $Email `
    --agree-tos `
    --no-eff-email `
    --non-interactive

Write-Host "=== Certificate issued successfully! Reloading Nginx ===" -ForegroundColor Green
docker compose exec nginx nginx -s reload

Write-Host "=== Testing Renewal Dry-Run ===" -ForegroundColor Green
docker compose exec certbot certbot renew --dry-run

Write-Host "=== Let's Encrypt SSL setup completed for $Domain ===" -ForegroundColor Green
