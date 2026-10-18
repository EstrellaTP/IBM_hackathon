"""Headers that authenticate a band or the simulator to ingest-api (issue #14).

``POST /api/v1/signal-batches`` requires ``X-Device-Key``. The key is read from the
``DEVICE_KEY`` environment variable or, on the VM, from ``infra/.env`` (where
``scripts/deploy_vm.sh`` generates it). It is never written to git.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / "infra" / ".env"


def device_key() -> str:
    """Return the device key from the environment or ``infra/.env`` ('' if absent)."""
    key = os.environ.get("DEVICE_KEY", "")
    if key or not ENV_FILE.exists():
        return key
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEVICE_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def device_headers() -> dict[str, str]:
    """JSON content type plus the device key."""
    return {"content-type": "application/json", "X-Device-Key": device_key()}
