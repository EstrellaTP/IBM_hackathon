"""HTTP routes of the detector service (internal: called by ``ingest-api``).

The service keeps one :class:`~services.detector.core.PatientDetector` per patient in
memory, so each patient's baseline stays strictly personal. A single process serves
all patients; the per-patient lock keeps batches of the same patient in order.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from services.common.schemas import EpisodeEvent, SignalBatch
from services.detector.registry import DetectorRegistry, get_registry

router = APIRouter(prefix="/api/v1", tags=["detector"])

RegistryDep = Annotated[DetectorRegistry, Depends(get_registry)]


class DetectionRequest(BaseModel):
    """A signal batch plus the time ``ingest-api`` received it (for latency stamps)."""

    batch: SignalBatch
    ingested_at: datetime | None = None


class DetectionResponse(BaseModel):
    """Episodes found in the batch and the detector version that found them."""

    episodes: list[EpisodeEvent]
    model_version: str


@router.post("/detections", response_model=DetectionResponse)
def detect(request: DetectionRequest, registry: RegistryDep) -> DetectionResponse:
    """Run the patient's personal detector over a new batch of samples."""
    episodes = registry.process(request.batch, request.ingested_at)
    return DetectionResponse(episodes=episodes, model_version=registry.model_version)
