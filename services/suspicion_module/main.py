"""suspicion-module service entry point: builds the FastAPI app (``uvicorn ...main:app``).

Suspicion module: when the clinician selects a suspicion (depression), computes
the features of the recording, runs the calibrated classifier and SHAP, and returns
a ModuleResult.
"""

from __future__ import annotations

from services.common.app import create_app
from services.suspicion_module.api import router

app = create_app("suspicion-module", router)
