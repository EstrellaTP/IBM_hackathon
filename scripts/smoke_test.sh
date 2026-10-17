#!/usr/bin/env bash
# Quality gate. Nothing is integrated into main unless this passes.
#   scripts/smoke_test.sh          -> unit tests + UI language check
#   scripts/smoke_test.sh --e2e    -> also the end-to-end check against a running stack
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== unit tests"
python3 -m pytest -q

echo "== UI language check (no diagnostic wording)"
if [ -d frontend ] && grep -RInE --include='*.html' --include='*.js' \
     -i "diagnos(is|ed|e)|has depression|suffers|wellbeing" frontend; then
  echo "FAIL: diagnostic wording found in the UI (see CLAUDE.md §5.5)"; exit 1
fi

if [ "${1:-}" = "--e2e" ]; then
  echo "== end-to-end"
  if [ -f tests/e2e/run_e2e.py ]; then
    python3 tests/e2e/run_e2e.py "${E2E_BASE_URL:-https://localhost:8443}"
  else
    echo "FAIL: tests/e2e/run_e2e.py does not exist yet"; exit 1
  fi
fi
echo "OK"
