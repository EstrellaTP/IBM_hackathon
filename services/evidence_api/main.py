"""evidence-api service entry point: builds the FastAPI app (``uvicorn ...main:app``).

Clinician-facing API: episode timeline with the patient's answers and the
evidence dashboard (ModuleResult per metric against reference ranges).
"""

from __future__ import annotations

from services.common.app import create_app
from services.evidence_api.api import router

app = create_app("evidence-api", router)
