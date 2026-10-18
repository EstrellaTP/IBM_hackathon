"""HTTP and WebSocket routes of ingest-api (patient side, routed by the gateway).

Thin layer over :mod:`services.ingest_api.core`; contract in ``docs/api.md``.
Access rules (issue #14): devices upload signal with ``X-Device-Key``; a patient token
is needed to answer (only their own episodes) and to open their question channel.
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

from services.common.auth import AuthError, ForbiddenError, check_patient_access
from services.common.schemas import (
    PATIENT_ID_PATTERN,
    EpisodeEvent,
    QuestionAnswer,
    Severity,
    SignalBatch,
    utcnow,
)
from services.common.security import (
    DeviceKeyDep,
    PatientDep,
    claims_from_token,
    forbidden,
    get_auth_settings,
    get_users,
)
from services.ingest_api.core import IngestPipeline, QuestionHub, UnknownEpisodeError
from services.ingest_api.settings import load_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["ingest-api"])

# Keep-alive so proxies do not close an idle question channel (nginx: 1 h read timeout).
PING_INTERVAL_SECONDS = 25
# WebSocket close codes in the private 4000-4999 range, mirroring HTTP 401 and 403.
WS_UNAUTHORIZED = 4401
WS_FORBIDDEN = 4403


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
    # ingested_at, detected_at, responded_at (UTC) and detector_inference_ms.
    timings: dict[str, datetime | float | None] = {}


class AnswerResponse(BaseModel):
    """Response to a stored answer."""

    episode_id: str
    stored_at: datetime


@router.post("/signal-batches", status_code=status.HTTP_202_ACCEPTED, response_model=IngestResponse)
async def ingest_signal_batch(
    batch: SignalBatch, pipeline: PipelineDep, _device: DeviceKeyDep
) -> IngestResponse:
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
        timings=result.timings,
    )


@router.post("/answers", status_code=status.HTTP_201_CREATED, response_model=AnswerResponse)
async def store_answer(
    answer: QuestionAnswer, pipeline: PipelineDep, claims: PatientDep
) -> AnswerResponse:
    """Store the patient's answer to one of their own questions."""
    try:
        owner = await pipeline.episode_owner(answer.episode_id)
    except httpx.HTTPError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store unavailable") from error
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown episode {answer.episode_id}")
    if owner != claims.patient_id:
        raise forbidden("this episode belongs to another patient")
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
    """Keep the phone's question channel open and push episodes as they happen.

    Browsers cannot set headers on a WebSocket, so the session token comes as
    ``?token=``. The handshake is accepted first so the close code reaches the page:
    4401 for a missing or invalid token, 4403 for another patient's channel or an
    origin not in ``ALLOWED_ORIGINS``.
    """
    await websocket.accept()
    code = _channel_refusal(websocket, patient_id)
    if code is not None:
        await websocket.close(code=code)
        return
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


def _channel_refusal(websocket: WebSocket, patient_id: str) -> int | None:
    """Return the close code if the caller may not open this channel, else ``None``."""
    origin = websocket.headers.get("origin")
    allowed = get_auth_settings().allowed_origins
    same_origin = origin is not None and origin.split("://", 1)[-1] == websocket.headers.get(
        "host", ""
    )
    if origin and allowed and origin not in allowed and not same_origin:
        logger.info("patient=%s channel refused: origin not allowed", patient_id)
        return WS_FORBIDDEN
    try:
        claims = claims_from_token(websocket.query_params.get("token", ""))
    except HTTPException:
        return WS_UNAUTHORIZED
    try:
        if claims.role != "patient":
            raise ForbiddenError("patients only")
        check_patient_access(claims, patient_id, get_users())
    except (ForbiddenError, AuthError):
        logger.info("patient=%s channel refused: token for another patient", patient_id)
        return WS_FORBIDDEN
    return None


async def _send_pending(websocket: WebSocket, patient_id: str, pipeline: IngestPipeline) -> None:
    """On (re)connection, send the single most relevant unanswered recent question.

    If the phone was disconnected (Android freezes backgrounded pages), several
    episodes may be waiting. Asking about all of them minutes later floods the patient
    and defeats the in-the-moment question, so only one is sent: an extreme one first
    (safety protocol), otherwise the newest. The others stay on the clinician's
    timeline as unanswered (issue #13).
    """
    with suppress(httpx.HTTPError):
        pending = await pipeline.pending_questions(patient_id)
        episode = select_pending_question(pending)
        if episode is None:
            return
        first_push = episode.timestamps.pushed_at is None
        if first_push:
            episode.timestamps.pushed_at = utcnow()
        await websocket.send_json({"type": "question", "episode": episode.model_dump(mode="json")})
        if first_push:
            await pipeline.mark_pushed(episode)
        logger.info(
            "patient=%s reconnect: sent episode=%s of %d pending",
            patient_id,
            episode.episode_id,
            len(pending),
        )


def select_pending_question(pending: list[EpisodeEvent]) -> EpisodeEvent | None:
    """Pick the question to send on reconnection: newest extreme, else newest."""
    if not pending:
        return None
    extreme = [e for e in pending if e.severity == Severity.EXTREME]
    return max(extreme or pending, key=lambda episode: episode.detected_at)
