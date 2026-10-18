"""ingest-api service entry point: builds the FastAPI app (``uvicorn ...main:app``).

Patient-facing ingestion: receives SignalBatch from the phone or the simulator,
stamps ``ingested_at``, asks the detector for episodes, stores everything and pushes
the in-the-moment question to the phone over WebSocket.
"""

from __future__ import annotations

from services.common.app import create_app
from services.ingest_api.api import router

app = create_app("ingest-api", router)
