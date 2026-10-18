"""Domain logic of the ingest-api service, free of web-framework imports.

Patient-facing ingestion: receives SignalBatch from the phone or the simulator,
stamps ``ingested_at``, asks the detector for episodes, stores everything and pushes
the in-the-moment question to the phone over WebSocket.
"""

from __future__ import annotations
