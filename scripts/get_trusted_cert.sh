#!/usr/bin/env bash
# Replace the self-signed demo certificate with a publicly trusted Let's Encrypt
# certificate for the VM's IP address, so browsers and phones show no warning.
#
# Runs ON THE VM, by a person who accepts the Let's Encrypt Subscriber Agreement
# (https://letsencrypt.org/repository/) by running it:
#
#     bash scripts/get_trusted_cert.sh 148.100.99.58            # staging test, then production
#     bash scripts/get_trusted_cert.sh 148.100.99.58 --renew    # used by the cron job
#
# Background (issue #8): Let's Encrypt issues IP-address certificates since January
# 2026, only with the 6-day "shortlived" profile, validated by HTTP-01 or TLS-ALPN-01.
# TLS-ALPN-01 listens on 443, already open in the VM firewall and unused (the gateway
# serves 8443). lego v5 has no s390x release binary; it is built from the official
# source with the official golang image (docs/vm-check.md). Note: issued certificates
# are logged publicly (Certificate Transparency), which publishes the IP address.
set -euo pipefail
cd "$(dirname "$0")/.."

IP="${1:?usage: get_trusted_cert.sh <public-ip> [--renew]}"
MODE="${2:-}"
LEGO="${LEGO:-$HOME/bin/lego}"
DATA="${LEGO_DATA:-$HOME/lego-data}"
STAGING="https://acme-staging-v02.api.letsencrypt.org/directory"
PRODUCTION="https://acme-v02.api.letsencrypt.org/directory"
CERT_DIR=infra/certs

if [ ! -x "$LEGO" ]; then
  mkdir -p "$(dirname "$LEGO")"
  docker run --rm -v "$(dirname "$LEGO")":/out -e GOBIN=/out -e CGO_ENABLED=0 \
    golang:1.26 go install github.com/go-acme/lego/v5@v5.5.2
fi

lego() {  # $1 = ACME server, $2 = data dir; lego v5 takes its options after "run"
  local server="$1" path="$2"
  sudo "$LEGO" run --server "$server" --path "$path" --accept-tos \
    --domains "$IP" --tls --profile shortlived
}

if [ "$MODE" = "--renew" ]; then
  # "run" renews only when due (by default when a third of the lifetime is left).
  lego "$PRODUCTION" "$DATA"
else
  # Separate data dirs: otherwise the production run finds the staging certificate,
  # considers it valid and skips the real issuance (seen on the first run).
  echo "== staging test (no rate limits, untrusted certificate)"
  lego "$STAGING" "$DATA-staging"
  echo "== production"
  lego "$PRODUCTION" "$DATA"
fi

sudo install -m 644 "$DATA/certificates/$IP.crt" "$CERT_DIR/tls.crt"
sudo install -m 644 "$DATA/certificates/$IP.key" "$CERT_DIR/tls.key"
docker compose -p holter -f infra/docker-compose.yml exec -T gateway nginx -s reload
echo "Installed the Let's Encrypt certificate for $IP and reloaded the gateway."

if [ "$MODE" != "--renew" ]; then
  line="0 */12 * * * cd $PWD && bash scripts/get_trusted_cert.sh $IP --renew >> $HOME/cert-renew.log 2>&1"
  # "|| true": with no crontab yet, crontab -l (and grep on empty input) exit 1, which
  # set -o pipefail would turn into an abort (seen on the first run).
  { crontab -l 2>/dev/null | grep -v get_trusted_cert.sh || true; echo "$line"; } | crontab -
  echo "Renewal checked every 12 hours (crontab)."
fi
