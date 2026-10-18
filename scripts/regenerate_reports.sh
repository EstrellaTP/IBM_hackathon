#!/usr/bin/env bash
# Regenerate every metric, table and figure of ml/reports/ from the raw data (F4-ML-01).
# Runs on the LinuxONE VM, where the data lives (about 30 minutes on 3 vCPUs):
#
#     bash scripts/regenerate_reports.sh            # writes to ~/reports_out
#     OUT=/some/dir bash scripts/regenerate_reports.sh
#
# Reports are written outside the repository copy because scripts/sync_to_vm.sh
# overwrites tracked files there; copy them back with scp and commit.
# The latency benchmark (tools/benchmark) is run separately, from a client machine.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-$HOME/venv-holter/bin/python}"
OUT="${OUT:-$HOME/reports_out}"
mkdir -p "$OUT"

step() { echo; echo "== $*"; }

step "datasets summary";          "$PY" -m ml.data.summarize_datasets > "$OUT/datasets_summary.md"
step "features (NHANES G+H, DEPRESJON)"; "$PY" -m ml.features.build --reports-dir "$OUT"
step "depression module training and validation"; "$PY" -m ml.models.train --reports-dir "$OUT"
step "reference ranges";          "$PY" -m ml.models.reference_ranges --out "$OUT/reference_ranges.json"
step "detector evaluation (WESAD)"; "$PY" -m ml.models.detector_evaluation --workers 3 --out-dir "$OUT"
step "NNPA comparison";           "$PY" -m ml.models.nnpa_comparison --out "$OUT"
step "done"; ls -la "$OUT"
