#!/usr/bin/env bash
# Quality gate. Nothing is integrated into main unless this passes.
#   scripts/smoke_test.sh          -> unit tests + UI language check
#   scripts/smoke_test.sh --e2e    -> also the end-to-end check against a running stack
set -euo pipefail
cd "$(dirname "$0")/.."

# Pick a working interpreter: python3 on Linux/the VM, python on Windows (Git Bash).
# Tools run as modules so they work even when their scripts dir is not on PATH.
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys" >/dev/null 2>&1; then
      PY="$candidate"; break
    fi
  done
fi
[ -n "$PY" ] || { echo "FAIL: no Python interpreter found (set PYTHON=...)"; exit 1; }

echo "== format and lint (ruff)"
"$PY" -m ruff format --check .
"$PY" -m ruff check .

echo "== unit tests"
"$PY" -m pytest -q

echo "== UI language check (no diagnostic wording)"
if [ -d frontend ] && grep -RInE --include='*.html' --include='*.js' \
     -i "diagnos(is|ed|e)|has depression|suffers|wellbeing" frontend; then
  echo "FAIL: diagnostic wording found in the UI (see CLAUDE.md §5.5)"; exit 1
fi

if [ "${1:-}" = "--e2e" ]; then
  echo "== end-to-end"
  if [ -f tests/e2e/run_e2e.py ]; then
    "$PY" tests/e2e/run_e2e.py "${E2E_BASE_URL:-https://localhost:8443}"
  else
    echo "FAIL: tests/e2e/run_e2e.py does not exist yet"; exit 1
  fi
fi
echo "OK"
