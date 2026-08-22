#!/bin/sh
set -eu

if [ -z "${DOMAIN:-}" ]; then
  echo "DOMAIN is required for the production Nginx TLS template." >&2
  exit 1
fi

cert_dir="/etc/letsencrypt/live/${DOMAIN}"
cert_file="${cert_dir}/fullchain.pem"
key_file="${cert_dir}/privkey.pem"
marker="/etc/letsencrypt/.medicore-placeholder-${DOMAIN}"

if [ -s "$cert_file" ] && [ -s "$key_file" ]; then
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to create the initial MediCORE placeholder TLS certificate." >&2
  exit 1
fi

mkdir -p "$cert_dir"
openssl req \
  -x509 \
  -nodes \
  -newkey rsa:2048 \
  -days 7 \
  -keyout "$key_file" \
  -out "$cert_file" \
  -subj "/CN=${DOMAIN}" >/dev/null 2>&1
touch "$marker"
echo "Created temporary self-signed TLS certificate for ${DOMAIN}. Run scripts/init_certbot.sh to replace it with Let's Encrypt."
