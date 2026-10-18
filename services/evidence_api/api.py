"""HTTP routes of evidence-api (clinician side, routed by the gateway).

Thin layer over :mod:`services.evidence_api.core`; contract in ``docs/api.md``.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from services.common.schemas import PATIENT_ID_PATTERN, EpisodeEvent, QuestionAnswer
from services.evidence_api.core import EvidenceReader
from services.evidence_api.settings import load_settings

router = APIRouter(prefix="/api/v1/clinician", tags=["evidence-api"])


@lru_cache(maxsize=1)
def get_reader() -> EvidenceReader:
    """Return the process-wide reader with one HTTP client."""
    settings = load_settings()
    return EvidenceReader(
        httpx.AsyncClient(timeout=settings.http_timeout_seconds), settings.store_url
    )


ReaderDep = Annotated[EvidenceReader, Depends(get_reader)]
PatientId = Annotated[str, Path(pattern=PATIENT_ID_PATTERN)]


class PatientSummary(BaseModel):
    """One row of the clinician's patient list."""

    patient_id: str
    episodes: int
    answered: int
    last_episode_at: datetime | None


class TimelineItem(BaseModel):
    """One episode with the patient's latest answer."""

    episode: EpisodeEvent
    answer: QuestionAnswer | None


class Timeline(BaseModel):
    """A patient's episodes, newest first."""

    patient_id: str
    items: list[TimelineItem]


@router.get("/patients", response_model=list[PatientSummary])
async def list_patients(reader: ReaderDep) -> list[PatientSummary]:
    """List patients with episodes."""
    try:
        return [PatientSummary(**row) for row in await reader.patients()]
    except httpx.HTTPError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store unavailable") from error


@router.get("/patients/{patient_id}/timeline", response_model=Timeline)
async def patient_timeline(patient_id: PatientId, reader: ReaderDep) -> Timeline:
    """Episode timeline with answers; the access is written to the audit log."""
    try:
        return Timeline(**await reader.timeline(patient_id))
    except httpx.HTTPError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store unavailable") from error
