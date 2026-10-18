"""Environment-based configuration of the ingest-api service (12-factor).

Variables (documented in ``infra/env.example``):

* ``DETECTOR_URL``: base URL of the detector service (``http://detector:8000``).
* ``STORE_URL``: base URL of the store service (``http://store:8000``).
* ``INGEST_HTTP_TIMEOUT_SECONDS``: timeout of calls to internal services (5).
* ``QUESTION_REPLAY_MINUTES``: unanswered questions of the last N minutes are sent
  again when the phone (re)connects (15).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class IngestSettings:
    """Configuration of ingest-api."""

    detector_url: str = "http://detector:8000"
    store_url: str = "http://store:8000"
    http_timeout_seconds: float = 5.0
    question_replay_minutes: float = 15.0


def load_settings(environ: dict[str, str] | None = None) -> IngestSettings:
    """Read the configuration from the environment, with safe defaults."""
    environ = dict(os.environ) if environ is None else environ
    defaults = IngestSettings()
    return IngestSettings(
        detector_url=environ.get("DETECTOR_URL", defaults.detector_url),
        store_url=environ.get("STORE_URL", defaults.store_url),
        http_timeout_seconds=float(
            environ.get("INGEST_HTTP_TIMEOUT_SECONDS", defaults.http_timeout_seconds)
        ),
        question_replay_minutes=float(
            environ.get("QUESTION_REPLAY_MINUTES", defaults.question_replay_minutes)
        ),
    )
