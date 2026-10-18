"""HTTP routes of suspicion-module (routed by the gateway as /api/v1/module-runs).

Thin layer: reads the patient's profile, activity history and episodes from the
store, runs :class:`services.suspicion_module.core.SuspicionModule` and writes the
audit entry for the inference (who, which module, which model version).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Annotated

import httpx
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status

from ml.models.predict import load_model
from services.common.schemas import AuditEntry, ModuleRequest, ModuleResult
from services.suspicion_module.core import InsufficientDataError, SuspicionModule
from services.suspicion_module.settings import SuspicionSettings, load_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["suspicion-module"])


@lru_cache(maxsize=1)
def get_settings() -> SuspicionSettings:
    """Process-wide settings."""
    return load_settings()


@lru_cache(maxsize=1)
def get_module() -> SuspicionModule:
    """Load the model and reference ranges once.

    Raises:
        FileNotFoundError: If the model has not been trained on this machine yet.
    """
    settings = get_settings()
    reference = json.loads(settings.reference_ranges_path.read_text(encoding="utf-8"))
    return SuspicionModule(load_model(settings.model_dir), reference)


@lru_cache(maxsize=1)
def get_client() -> httpx.AsyncClient:
    """Shared HTTP client for the store."""
    settings = get_settings()
    return httpx.AsyncClient(base_url=settings.store_url, timeout=settings.http_timeout_seconds)


ClientDep = Annotated[httpx.AsyncClient, Depends(get_client)]


def _module() -> SuspicionModule:
    try:
        return get_module()
    except FileNotFoundError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "model not available: train it on the VM with python3 -m ml.models.train",
        ) from error


ModuleDep = Annotated[SuspicionModule, Depends(_module)]


@router.post("/module-runs", response_model=ModuleResult)
async def run_module(request: ModuleRequest, client: ClientDep, module: ModuleDep) -> ModuleResult:
    """Run the module selected by the clinician over the patient's recording."""
    patient = request.patient_id
    profile_response = await client.get(f"/api/v1/patients/{patient}/profile")
    if profile_response.status_code == httpx.codes.NOT_FOUND:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no recording for {patient}")
    profile_response.raise_for_status()
    profile = profile_response.json()
    hours = (await client.get(f"/api/v1/patients/{patient}/activity-hours")).json()
    episodes = (await client.get("/api/v1/episodes", params={"patient_id": patient})).json()
    if not hours or not profile.get("recording_start"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no activity history")
    try:
        result = module.run(
            request,
            pd.DataFrame(hours),
            profile["sex"],
            profile["age_group"],
            pd.Timestamp(profile["recording_start"]).date(),
            [episode["episode_id"] for episode in episodes],
        )
    except InsufficientDataError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    audit = AuditEntry(
        actor=request.requested_by,
        action="module_run",
        patient_id=patient,
        model_version=result.model_version,
        detail={
            "suspicion": request.suspicion.value,
            "result": result.result.value,
            "valid_days": result.data_quality.valid_days,
        },
    )
    (
        await client.post("/api/v1/audit-entries", json=audit.model_dump(mode="json"))
    ).raise_for_status()
    return result
