#!/usr/bin/env bash
# Copy the working tree to the LinuxONE VM over SSH, without needing GitHub
# credentials on the VM (the repository may be private).
#
#     scripts/sync_to_vm.sh            # host alias "l1cc", target ~/IBM_hackathon
#     VM_HOST=other VM_DIR=/srv/app scripts/sync_to_vm.sh
#
# Only files tracked by git or untracked-but-not-ignored are sent, so .env files,
# keys and datasets listed in .gitignore never leave the laptop through this script.
# Files are extracted over the existing copy; nothing on the VM is deleted (data in
# ml/data/raw/ lives there and must survive syncs).
set -euo pipefail
cd "$(dirname "$0")/.."

VM_HOST="${VM_HOST:-l1cc}"
VM_DIR="${VM_DIR:-IBM_hackathon}"

# Exclude deleted-but-still-tracked paths, which tar cannot read.
git ls-files -z --cached --others --exclude-standard \
  | xargs -0 -I{} sh -c 'test -e "{}" && printf "%s\0" "{}"' \
  | tar --null -T - -cf - \
  | ssh -o BatchMode=yes "$VM_HOST" "mkdir -p '$VM_DIR' && tar -xf - -C '$VM_DIR'"

echo "Synced $(git rev-parse --short HEAD)$(git diff --quiet || echo '+dirty') to $VM_HOST:$VM_DIR"
