#!/usr/bin/env bash
# One-command deployment of the whole stack on the LinuxONE VM, from the laptop:
#
#     scripts/deploy_vm.sh                      # host alias l1cc, dir ~/IBM_hackathon
#     VM_DIR=holter-clean scripts/deploy_vm.sh  # deploy into a fresh directory
#
# Steps: copy the repo (git-tracked files only), create the TLS certificate and the
# .env with a fresh Fernet key on the VM if they do not exist yet (secrets are
# generated on the VM and never leave it), then build and start docker compose and
# wait until every container is healthy.
set -euo pipefail
cd "$(dirname "$0")/.."

VM_HOST="${VM_HOST:-l1cc}"
VM_DIR="${VM_DIR:-IBM_hackathon}"
PUBLIC_HOST="${PUBLIC_HOST:-148.100.99.58}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-holter}"

VM_HOST="$VM_HOST" VM_DIR="$VM_DIR" scripts/sync_to_vm.sh

ssh -o BatchMode=yes "$VM_HOST" bash -s -- "$VM_DIR" "$PUBLIC_HOST" "$COMPOSE_PROJECT" <<'REMOTE'
set -euo pipefail
cd "$1"
PUBLIC_HOST="$2"
PROJECT="$3"
[ -f infra/certs/tls.crt ] || bash scripts/make_dev_cert.sh "$PUBLIC_HOST"
if [ ! -f infra/.env ]; then
  cp infra/env.example infra/.env
  # Fernet key = 32 random bytes, URL-safe base64 (no Python packages needed).
  key=$(head -c 32 /dev/urandom | base64 | tr '+/' '-_')
  sed -i "s|^STORE_ENCRYPTION_KEY=.*|STORE_ENCRYPTION_KEY=$key|" infra/.env
  chmod 600 infra/.env
  echo "Created infra/.env with a new encryption key"
fi
compose="docker compose -p $PROJECT -f infra/docker-compose.yml --env-file infra/.env"
$compose up -d --build --wait --wait-timeout 300
$compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"
REMOTE
echo "Deployed. Open https://$PUBLIC_HOST:8443/"
