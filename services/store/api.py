"""HTTP routes of the store service (internal: not routed by the gateway).

Thin layer over :class:`services.store.core.EncryptedStore`; see ``docs/api.md``.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from services.common.schemas import (
    PATIENT_ID_PATTERN,
    AuditEntry,
    EpisodeEvent,
    QuestionAnswer,
    SignalBatch,
)
from services.store.core import EncryptedStore, UnknownEpisodeError
from services.store.settings import load_settings

router = APIRouter(prefix="/api/v1", tags=["store"])


@lru_cache(maxsize=1)
def get_store() -> EncryptedStore:
    """Return the process-wide store, opened on first use from the environment."""
    settings = load_settings()
    return EncryptedStore(settings.db_path, settings.encryption_key)


StoreDep = Annotated[EncryptedStore, Depends(get_store)]
PatientIdQuery = Annotated[str, Query(pattern=PATIENT_ID_PATTERN)]
OptionalPatientIdQuery = Annotated[str | None, Query(pattern=PATIENT_ID_PATTERN)]


class StoredBatch(BaseModel):
    """Response to a stored signal batch."""

    batch_id: int
    sample_count: int


class StoredAnswer(BaseModel):
    """Response to a stored answer."""

    episode_id: str
    stored_at: datetime


class TimelineItemOut(BaseModel):
    """One episode with the latest answer."""

    episode: EpisodeEvent
    answer: QuestionAnswer | None


class Timeline(BaseModel):
    """A patient's episodes, newest first."""

    patient_id: str
    items: list[TimelineItemOut]


class PatientSummaryOut(BaseModel):
    """Per-patient counts."""

    patient_id: str
    episodes: int
    answered: int
    last_episode_at: datetime | None


class AuditVerification(BaseModel):
    """Result of recomputing the audit hash chain."""

    valid: bool
    entries: int


@router.post("/signal-batches", status_code=status.HTTP_201_CREATED, response_model=StoredBatch)
def store_signal_batch(batch: SignalBatch, store: StoreDep) -> StoredBatch:
    """Store a batch of samples encrypted at rest."""
    return StoredBatch(batch_id=store.add_signal_batch(batch), sample_count=len(batch.samples))


@router.post("/episodes", status_code=status.HTTP_201_CREATED, response_model=EpisodeEvent)
def store_episode(episode: EpisodeEvent, store: StoreDep) -> EpisodeEvent:
    """Store (or update, same id) an episode."""
    store.add_episode(episode)
    return episode


@router.get("/episodes", response_model=list[EpisodeEvent])
def list_episodes(
    patient_id: PatientIdQuery,
    store: StoreDep,
) -> list[EpisodeEvent]:
    """List a patient's episodes, newest first."""
    return store.list_episodes(patient_id)


@router.get("/episodes/{episode_id}", response_model=EpisodeEvent)
def get_episode(episode_id: str, store: StoreDep) -> EpisodeEvent:
    """Return one episode."""
    episode = store.get_episode(episode_id)
    if episode is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown episode {episode_id}")
    return episode


@router.post("/answers", status_code=status.HTTP_201_CREATED, response_model=StoredAnswer)
def store_answer(answer: QuestionAnswer, store: StoreDep) -> StoredAnswer:
    """Store the patient's answer to an episode."""
    try:
        stored_at = store.add_answer(answer)
    except UnknownEpisodeError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown episode {error}") from error
    return StoredAnswer(episode_id=answer.episode_id, stored_at=stored_at)


@router.get("/patients", response_model=list[PatientSummaryOut])
def list_patients(store: StoreDep) -> list[PatientSummaryOut]:
    """List patients with episodes, most recent first."""
    return [PatientSummaryOut(**vars(summary)) for summary in store.list_patients()]


@router.get("/patients/{patient_id}/timeline", response_model=Timeline)
def patient_timeline(patient_id: str, store: StoreDep) -> Timeline:
    """Return a patient's episodes with their latest answers."""
    items = [
        TimelineItemOut(episode=i.episode, answer=i.answer) for i in store.timeline(patient_id)
    ]
    return Timeline(patient_id=patient_id, items=items)


@router.post("/audit-entries", status_code=status.HTTP_201_CREATED)
def append_audit_entry(entry: AuditEntry, store: StoreDep) -> dict[str, str]:
    """Append an entry to the tamper-evident audit log."""
    return {"hash": store.add_audit_entry(entry)}


@router.get("/audit-entries", response_model=list[AuditEntry])
def list_audit_entries(
    store: StoreDep,
    patient_id: OptionalPatientIdQuery = None,
) -> list[AuditEntry]:
    """List audit entries in insertion order."""
    return store.list_audit_entries(patient_id)


@router.get("/audit-entries/verification", response_model=AuditVerification)
def verify_audit_entries(store: StoreDep) -> AuditVerification:
    """Recompute the audit hash chain and report whether it is intact."""
    valid, entries = store.verify_audit_chain()
    return AuditVerification(valid=valid, entries=entries)
