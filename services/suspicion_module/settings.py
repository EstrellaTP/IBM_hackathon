"""Environment-based configuration of the suspicion-module service (12-factor).

* ``STORE_URL``: base URL of the store (``http://store:8000``).
* ``SUSPICION_MODEL_DIR``: directory with ``depression_model.json`` (``/models``,
  mounted read-only from ``ml/models/artifacts`` on the VM).
* ``REFERENCE_RANGES_PATH``: NHANES reference bands
  (``/app/ml/reports/reference_ranges.json`` inside the image).
* ``SUSPICION_HTTP_TIMEOUT_SECONDS``: timeout of calls to the store (10).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SuspicionSettings:
    """Configuration of suspicion-module."""

    store_url: str = "http://store:8000"
    model_dir: Path = Path("/models")
    reference_ranges_path: Path = Path("/app/ml/reports/reference_ranges.json")
    http_timeout_seconds: float = 10.0


def load_settings(environ: dict[str, str] | None = None) -> SuspicionSettings:
    """Read the configuration from the environment, with safe defaults."""
    environ = dict(os.environ) if environ is None else environ
    defaults = SuspicionSettings()
    return SuspicionSettings(
        store_url=environ.get("STORE_URL", defaults.store_url),
        model_dir=Path(environ.get("SUSPICION_MODEL_DIR", defaults.model_dir)),
        reference_ranges_path=Path(
            environ.get("REFERENCE_RANGES_PATH", defaults.reference_ranges_path)
        ),
        http_timeout_seconds=float(
            environ.get("SUSPICION_HTTP_TIMEOUT_SECONDS", defaults.http_timeout_seconds)
        ),
    )
