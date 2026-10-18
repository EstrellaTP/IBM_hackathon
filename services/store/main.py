"""store service entry point: builds the FastAPI app (``uvicorn ...main:app``).

Encrypted, pseudonymised storage: signal batches, episodes, answers and the
append-only audit log. Sensitive fields are encrypted at rest with Fernet.
"""

from __future__ import annotations

from services.common.app import create_app
from services.store.api import router

app = create_app("store", router)
