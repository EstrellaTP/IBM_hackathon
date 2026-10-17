#!/usr/bin/env bash
# Print a reproducible transcript of the LinuxONE VM capabilities that matter for
# the project: architecture and byte order, CPU facilities (nnpa), resources,
# Docker, CPACF hardware crypto, Secure Execution and the NNPA check via zDNN.
#
# Runs on the VM. From the laptop:
#     ssh l1cc 'bash -s' < scripts/vm_check.sh > docs/screenshots/vm_check.txt
# Requires tools/vm_check/nnpa_check.c to be present at $NNPA_SRC on the VM for the
# NNPA section (it is skipped otherwise). No secrets or health data are printed.
set -uo pipefail

NNPA_SRC="${NNPA_SRC:-$HOME/IBM_hackathon/tools/vm_check/nnpa_check.c}"

run() {
  # Echo the command like a terminal prompt, then its output.
  echo "\$ $*"
  bash -c "$*" 2>&1
  echo
}

echo "# LinuxONE VM check - $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo
run "uname -m"
run "uname -srv"
run "grep PRETTY_NAME /etc/os-release"
run "lscpu | grep -E 'Architecture|Byte Order|^CPU\\(s\\)|Machine type|CPU static MHz|Hypervisor|Flags'"
run "grep -o -w nnpa /proc/cpuinfo | head -1"
run "nproc && free -h | head -2"
run "df -h /"
run "python3 --version"
run "docker version --format 'client={{.Client.Version}} server={{.Server.Version}} os/arch={{.Server.Os}}/{{.Server.Arch}}'"
run "docker compose version"
run "docker run --rm python:3.12-slim python -c 'import platform, sys; print(platform.machine(), sys.byteorder)'"
run "lsmod | grep -E '^(aes_s390|sha256_s390|sha3_256_s390|ghash_s390|pkey|zcrypt) '"
run "icainfo | grep -E 'function|AES (CBC|GCM)|SHA-256|ECDSA Sign|X25519 Derive'"
run "lszcrypt"
run "test -e /sys/firmware/uv/prot_virt_guest && cat /sys/firmware/uv/prot_virt_guest || echo 'not a Secure Execution guest (no /sys/firmware/uv)'"
if [ -f "$NNPA_SRC" ]; then
  run "gcc -O2 -o /tmp/nnpa_check '$NNPA_SRC' -lzdnn && /tmp/nnpa_check"
else
  echo "(NNPA check skipped: $NNPA_SRC not found)"
fi
