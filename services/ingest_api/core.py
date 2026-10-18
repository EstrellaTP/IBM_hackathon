"""Real-time path: signal batch -> detector -> question on the phone -> store.

Role in the architecture (CLAUDE.md sections 5.1 and 8): this is the code on the
critical path of the in-the-moment question. For every ``SignalBatch`` it:

1. stamps ``ingested_at`` (server-side start of the latency measurement);
2. asks the detector for episodes and stores the batch, concurrently;
3. pushes each episode to the patient's phone over WebSocket, stamping ``pushed_at``
   right before the write, so the stored timestamps separate network from server time;
4. stores each episode and an audit entry for the inference.

The question is pushed *before* storing it: the patient should not wait for the
database. If no phone is connected, the episode is stored without ``pushed_at`` and
sent when the phone connects (see :meth:`QuestionHub.connect`).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from services.common.schemas import (
    AuditEntry,
    EpisodeEvent,
    QuestionAnswer,
    SignalBatch,
    utcnow,
)

logger = logging.getLogger(__name__)


class QuestionSocket(Protocol):
    """The part of a WebSocket the hub needs (lets tests use a fake)."""

    async def send_json(self, data: dict) -> None:
        """Send one JSON message."""


class UnknownEpisodeError(LookupError):
    """The store does not know the episode an answer refers to."""


@dataclass
class QuestionHub:
    """Keeps the phones connected per patient and pushes questions to them."""

    _sockets: dict[str, set[QuestionSocket]] = field(default_factory=lambda: defaultdict(set))

    def connected(self, patient_id: str) -> int:
        """Number of open sockets for a patient."""
        return len(self._sockets.get(patient_id, ()))

    def add(self, patient_id: str, socket: QuestionSocket) -> None:
        """Register a phone's socket."""
        self._sockets[patient_id].add(socket)
        logger.info("patient=%s phone connected (%d open)", patient_id, self.connected(patient_id))

    def remove(self, patient_id: str, socket: QuestionSocket) -> None:
        """Forget a closed socket."""
        self._sockets.get(patient_id, set()).discard(socket)

    async def push(self, episode: EpisodeEvent) -> bool:
        """Send an episode to every phone of its patient, stamping ``pushed_at``.

        Returns:
            Whether at least one phone received it.
        """
        sockets = list(self._sockets.get(episode.patient_id, ()))
        if not sockets:
            return False
        episode.timestamps.pushed_at = utcnow()
        message = {"type": "question", "episode": episode.model_dump(mode="json")}
        delivered = False
        for socket in sockets:
            try:
                await socket.send_json(message)
                delivered = True
            except Exception as error:  # noqa: BLE001 - a broken socket must not stop the others
                logger.warning(
                    "patient=%s push failed: %s", episode.patient_id, type(error).__name__
                )
                self.remove(episode.patient_id, socket)
        return delivered


@dataclass
class IngestResult:
    """Outcome of one batch."""

    patient_id: str
    accepted_samples: int
    episodes: list[EpisodeEvent]
    timings: dict[str, datetime | float | None] = field(default_factory=dict)


class IngestPipeline:
    """Orchestrates detector, phone push, store and audit for each batch.

    Args:
        client: HTTP client used for the internal services.
        detector_url: Base URL of the detector.
        store_url: Base URL of the store.
        hub: Phones connected over WebSocket.
        question_replay: Age of unanswered questions re-sent on (re)connection.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        detector_url: str,
        store_url: str,
        hub: QuestionHub,
        question_replay: timedelta = timedelta(minutes=15),
    ) -> None:
        self._client = client
        self._detector_url = detector_url.rstrip("/")
        self._store_url = store_url.rstrip("/")
        self.hub = hub
        self._question_replay = question_replay

    async def ingest(self, batch: SignalBatch) -> IngestResult:
        """Process one batch end to end and return the episodes it produced."""
        ingested_at = utcnow()
        # Serialise the batch once with Pydantic's Rust encoder and reuse the bytes for
        # both internal calls: the benchmark showed ingest-api CPU-bound at 1,000
        # patients, mostly from converting the batch to dicts and re-encoding it twice.
        batch_json = batch.model_dump_json().encode()
        detection_body = (
            b'{"batch":'
            + batch_json
            + b',"ingested_at":"'
            + ingested_at.isoformat().encode()
            + b'"}'
        )
        headers = {"content-type": "application/json"}
        detection, _ = await asyncio.gather(
            self._client.post(
                f"{self._detector_url}/api/v1/detections", content=detection_body, headers=headers
            ),
            self._client.post(
                f"{self._store_url}/api/v1/signal-batches", content=batch_json, headers=headers
            ),
        )
        detection.raise_for_status()
        detected_at = utcnow()
        payload = detection.json()
        episodes = [EpisodeEvent.model_validate(item) for item in payload["episodes"]]
        for episode in episodes:
            await self.hub.push(episode)
            await self._store_episode(episode)
            logger.info(
                "patient=%s episode=%s severity=%s server_ms=%s",
                episode.patient_id,
                episode.episode_id,
                episode.severity.value,
                _rounded(episode.timestamps.server_latency_ms()),
            )
        await self._audit(
            AuditEntry(
                actor="detector",
                action="episode_inference",
                patient_id=batch.patient_id,
                model_version=payload.get("model_version"),
                detail={
                    "samples": len(batch.samples),
                    "episodes": len(episodes),
                    "episode_ids": ",".join(e.episode_id for e in episodes) or None,
                },
            )
        )
        # Server-side stage times, so the benchmark separates server from network.
        timings = {
            "ingested_at": ingested_at,
            "detected_at": detected_at,
            "responded_at": utcnow(),
            "detector_inference_ms": payload.get("inference_ms"),
        }
        return IngestResult(batch.patient_id, len(batch.samples), episodes, timings)

    async def store_answer(self, answer: QuestionAnswer) -> dict:
        """Forward the patient's answer to the store and audit it.

        Raises:
            UnknownEpisodeError: If the store does not know the episode.
        """
        response = await self._client.post(
            f"{self._store_url}/api/v1/answers", json=answer.model_dump(mode="json")
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            raise UnknownEpisodeError(answer.episode_id)
        response.raise_for_status()
        episode = await self._find_episode(answer.episode_id)
        if episode is not None:
            await self._audit(
                AuditEntry(
                    actor="patient",
                    action="answer_stored",
                    patient_id=episode.patient_id,
                    detail={
                        "episode_id": answer.episode_id,
                        "safety_action": answer.safety_action.value
                        if answer.safety_action
                        else None,
                    },
                )
            )
        return response.json()

    async def pending_questions(self, patient_id: str) -> list[EpisodeEvent]:
        """Recent unanswered episodes of a patient, oldest first (sent on connect)."""
        response = await self._client.get(
            f"{self._store_url}/api/v1/patients/{patient_id}/timeline"
        )
        response.raise_for_status()
        cutoff = utcnow() - self._question_replay
        pending = [
            EpisodeEvent.model_validate(item["episode"])
            for item in response.json()["items"]
            if item["answer"] is None
        ]
        return sorted((e for e in pending if e.detected_at >= cutoff), key=lambda e: e.detected_at)

    async def mark_pushed(self, episode: EpisodeEvent) -> None:
        """Store an episode again after a late push, keeping its ``pushed_at``."""
        await self._store_episode(episode)

    async def _store_episode(self, episode: EpisodeEvent) -> None:
        response = await self._client.post(
            f"{self._store_url}/api/v1/episodes", json=episode.model_dump(mode="json")
        )
        response.raise_for_status()

    async def _find_episode(self, episode_id: str) -> EpisodeEvent | None:
        # The answer only carries the episode id; the audit entry needs the patient.
        response = await self._client.get(f"{self._store_url}/api/v1/episodes/{episode_id}")
        if response.status_code != httpx.codes.OK:
            return None
        return EpisodeEvent.model_validate(response.json())

    async def _audit(self, entry: AuditEntry) -> None:
        try:
            response = await self._client.post(
                f"{self._store_url}/api/v1/audit-entries", json=entry.model_dump(mode="json")
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            # The question has already reached the patient; log loudly but do not fail it.
            logger.error("audit write failed for patient=%s: %s", entry.patient_id, error)


def _rounded(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
