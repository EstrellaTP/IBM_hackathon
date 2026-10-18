"""HTTP routes of evidence-api: login, patient self-view and clinician views.

Thin layer over :mod:`services.evidence_api.core`; contract in ``docs/api.md``.
Access rules (issue #14): a patient reads only their own timeline; a clinician reads
only the patients assigned to them; every data access is audited with the username.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field

from services.common.auth import AuthError, assigned_patients, issue_token, require_secret
from services.common.schemas import PATIENT_ID_PATTERN, EpisodeEvent, QuestionAnswer
from services.common.security import (
    ClinicianDep,
    PatientDep,
    UsersDep,
    ensure_access,
    get_auth_settings,
    unauthorized,
)
from services.evidence_api.core import EvidenceReader
from services.evidence_api.settings import load_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/clinician", tags=["evidence-api"])
public_router = APIRouter(prefix="/api/v1", tags=["sessions"])


@lru_cache(maxsize=1)
def get_reader() -> EvidenceReader:
    """Return the process-wide reader with one HTTP client."""
    settings = load_settings()
    return EvidenceReader(
        httpx.AsyncClient(timeout=settings.http_timeout_seconds), settings.store_url
    )


ReaderDep = Annotated[EvidenceReader, Depends(get_reader)]
PatientId = Annotated[str, Path(pattern=PATIENT_ID_PATTERN)]


class Credentials(BaseModel):
    """Login form."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class Session(BaseModel):
    """A signed session token and what the frontend needs to route the user."""

    token: str
    role: Literal["patient", "clinician"]
    display_name: str
    patient_id: str | None
    expires_at: datetime


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


@public_router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=Session)
def create_session(credentials: Credentials, users: UsersDep) -> Session:
    """Log in as patient or clinician; returns a 12-hour signed token."""
    try:
        user = users.authenticate(credentials.username, credentials.password)
        token, expires = issue_token(user, require_secret(get_auth_settings().token_secret))
    except AuthError as error:
        logger.info("login refused")
        raise unauthorized("invalid username or password") from error
    logger.info("login user=%s role=%s", user.username, user.role)
    return Session(
        token=token,
        role=user.role,
        display_name=user.display_name or user.username,
        patient_id=user.patient_id,
        expires_at=datetime.fromtimestamp(expires, tz=timezone.utc),
    )


@public_router.get("/patients/me/timeline", response_model=Timeline)
async def own_timeline(claims: PatientDep, reader: ReaderDep) -> Timeline:
    """A patient sees their own episodes and answers (patient control, CLAUDE.md 11)."""
    try:
        return Timeline(**await reader.timeline(claims.patient_id, viewer=claims.sub))
    except httpx.HTTPError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store unavailable") from error


@router.get("/patients", response_model=list[PatientSummary])
async def list_patients(
    claims: ClinicianDep, users: UsersDep, reader: ReaderDep
) -> list[PatientSummary]:
    """List the patients assigned to this clinician that have episodes."""
    allowed = set(assigned_patients(claims, users))
    try:
        rows = await reader.patients()
    except httpx.HTTPError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store unavailable") from error
    return [PatientSummary(**row) for row in rows if row["patient_id"] in allowed]


@router.get("/patients/{patient_id}/timeline", response_model=Timeline)
async def patient_timeline(
    patient_id: PatientId, claims: ClinicianDep, users: UsersDep, reader: ReaderDep
) -> Timeline:
    """Episode timeline with answers; the access is written to the audit log."""
    ensure_access(claims, patient_id, users)
    try:
        return Timeline(**await reader.timeline(patient_id, viewer=claims.sub))
    except httpx.HTTPError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store unavailable") from error
