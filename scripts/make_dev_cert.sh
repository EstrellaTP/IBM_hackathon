#!/usr/bin/env bash
# Create a self-signed TLS certificate for the gateway (demo only; certs/ is gitignored).
#     scripts/make_dev_cert.sh [public-ip-or-hostname]
# Browsers and phones will show a warning that must be accepted once.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${1:-${PUBLIC_HOST:-localhost}}"
OUT=infra/certs
mkdir -p "$OUT"
if [[ "$HOST" =~ ^[0-9.]+$ ]]; then SAN="IP:$HOST,DNS:localhost,IP:127.0.0.1"; else SAN="DNS:$HOST,DNS:localhost,IP:127.0.0.1"; fi
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 30 \
  -subj "/CN=$HOST/O=GigaFly demo" -addext "subjectAltName=$SAN" \
  -keyout "$OUT/tls.key" -out "$OUT/tls.crt" 2>/dev/null
# The unprivileged nginx user (uid 101) must be able to read the key.
chmod 644 "$OUT/tls.key" "$OUT/tls.crt"
echo "Wrote $OUT/tls.crt and $OUT/tls.key for $HOST ($SAN)"
