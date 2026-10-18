"""HTTP and WebSocket routes of ingest-api (patient side, routed by the gateway).

Thin layer over :mod:`services.ingest_api.core`; contract in ``docs/api.md``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from services.common.schemas import (
    PATIENT_ID_PATTERN,
    EpisodeEvent,
    QuestionAnswer,
    SignalBatch,
    utcnow,
)
from services.ingest_api.core import IngestPipeline, QuestionHub, UnknownEpisodeError
from services.ingest_api.settings import load_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["ingest-api"])

# Keep-alive so proxies do not close an idle question channel (nginx: 1 h read timeout).
PING_INTERVAL_SECONDS = 25


@lru_cache(maxsize=1)
def get_pipeline() -> IngestPipeline:
    """Return the process-wide pipeline (one HTTP client, one hub of phones)."""
    settings = load_settings()
    client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    return IngestPipeline(
        client,
        settings.detector_url,
        settings.store_url,
        QuestionHub(),
        timedelta(minutes=settings.question_replay_minutes),
    )


PipelineDep = Annotated[IngestPipeline, Depends(get_pipeline)]
PatientId = Annotated[str, Path(pattern=PATIENT_ID_PATTERN)]


class IngestResponse(BaseModel):
    """Response to a signal batch."""

    patient_id: str
    accepted_samples: int
    episodes: list[EpisodeEvent]


class AnswerResponse(BaseModel):
    """Response to a stored answer."""

    episode_id: str
    stored_at: datetime


@router.post("/signal-batches", status_code=status.HTTP_202_ACCEPTED, response_model=IngestResponse)
async def ingest_signal_batch(batch: SignalBatch, pipeline: PipelineDep) -> IngestResponse:
    """Receive a minute of signal, detect episodes and push questions to the phone."""
    try:
        result = await pipeline.ingest(batch)
    except httpx.HTTPError as error:
        logger.error("patient=%s internal service error: %s", batch.patient_id, error)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "detector or store unavailable"
        ) from error
    return IngestResponse(
        patient_id=result.patient_id,
        accepted_samples=result.accepted_samples,
        episodes=result.episodes,
    )


@router.post("/answers", status_code=status.HTTP_201_CREATED, response_model=AnswerResponse)
async def store_answer(answer: QuestionAnswer, pipeline: PipelineDep) -> AnswerResponse:
    """Store the patient's answer to a question."""
    try:
        stored = await pipeline.store_answer(answer)
    except UnknownEpisodeError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown episode {error}") from error
    except httpx.HTTPError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store unavailable") from error
    return AnswerResponse(**stored)


@router.websocket("/patients/{patient_id}/questions")
async def question_channel(
    websocket: WebSocket, patient_id: PatientId, pipeline: PipelineDep
) -> None:
    """Keep the phone's question channel open and push episodes as they happen."""
    await websocket.accept()
    pipeline.hub.add(patient_id, websocket)
    try:
        await _send_pending(websocket, patient_id, pipeline)
        while True:
            # Wait for a client message (ignored) or send a ping after the interval.
            try:
                await asyncio.wait_for(websocket.receive_text(), PING_INTERVAL_SECONDS)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        logger.info("patient=%s phone disconnected", patient_id)
    finally:
        pipeline.hub.remove(patient_id, websocket)


async def _send_pending(websocket: WebSocket, patient_id: str, pipeline: IngestPipeline) -> None:
    """Re-send recent unanswered questions, e.g. after the phone lost connection."""
    with suppress(httpx.HTTPError):
        for episode in await pipeline.pending_questions(patient_id):
            first_push = episode.timestamps.pushed_at is None
            if first_push:
                episode.timestamps.pushed_at = utcnow()
            await websocket.send_json(
                {"type": "question", "episode": episode.model_dump(mode="json")}
            )
            if first_push:
                await pipeline.mark_pushed(episode)
