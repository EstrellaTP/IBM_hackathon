"""Environment-based configuration of the evidence-api service (12-factor).

* ``STORE_URL``: base URL of the store service (``http://store:8000``).
* ``EVIDENCE_HTTP_TIMEOUT_SECONDS``: timeout of calls to the store (5).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceSettings:
    """Configuration of evidence-api."""

    store_url: str = "http://store:8000"
    http_timeout_seconds: float = 5.0


def load_settings(environ: dict[str, str] | None = None) -> EvidenceSettings:
    """Read the configuration from the environment, with safe defaults."""
    environ = dict(os.environ) if environ is None else environ
    defaults = EvidenceSettings()
    return EvidenceSettings(
        store_url=environ.get("STORE_URL", defaults.store_url),
        http_timeout_seconds=float(
            environ.get("EVIDENCE_HTTP_TIMEOUT_SECONDS", defaults.http_timeout_seconds)
        ),
    )
