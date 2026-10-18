"""detector service entry point: builds the FastAPI app (``uvicorn ...main:app``).

Real-time episode detection: keeps one personal-baseline detector per patient
and turns each SignalBatch into zero or more EpisodeEvents (see ``core.py``).
"""

from __future__ import annotations

from services.common.app import create_app
from services.detector.api import router

app = create_app("detector", router)
