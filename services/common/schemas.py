"""Shared data contracts for every service, the simulator and the frontend.

These models are the single source of truth for messages exchanged between
components (see CLAUDE.md section 9). Change them only through a dedicated PR
and announce the change in docs/HANDOFF.md.

Health data never leaves LinuxONE. Patient identifiers are random pseudonyms
(``p_`` + hex); no real identity is ever stored.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0.0"

PATIENT_ID_PATTERN = r"^p_[0-9a-f]{4,32}$"
EPISODE_ID_PATTERN = r"^e_[0-9a-f]{4,32}$"


def utcnow() -> datetime:
    """Timezone-aware current time in UTC. Use it for every timestamp."""
    return datetime.now(timezone.utc)


def new_patient_id() -> str:
    return f"p_{secrets.token_hex(8)}"


def new_episode_id() -> str:
    return f"e_{secrets.token_hex(8)}"


class _Contract(BaseModel):
    """Base for all contracts: strict field names, aware datetimes."""

    model_config = ConfigDict(extra="forbid", frozen=False)


def _require_tz(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware (use UTC)")
    return value


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class Device(str, Enum):
    E4 = "e4"            # Empatica E4 (nurse stress dataset)
    WESAD = "wesad"      # WESAD replay
    POLAR = "polar"      # real Bluetooth HR band (optional demo)
    SIM = "sim"          # synthetic data


class Severity(str, Enum):
    NORMAL = "normal"
    EXTREME = "extreme"  # triggers the safety protocol ("Are you OK?")


class DetectionMethod(str, Enum):
    ZSCORE = "zscore"
    IFOREST = "iforest"
    FIXED_RULE = "fixed_rule"  # baseline for comparison only (e.g. HR > 100)


class Activity(str, Enum):
    WORK = "work"
    REST = "rest"
    SOCIAL = "social"
    COMMUTE = "commute"
    OTHER = "other"


class SafetyAction(str, Enum):
    # Simulated only: the system never calls anyone on its own.
    CALL_112_SIMULATED = "call_112_simulated"
    NOTIFY_CONTACT_SIMULATED = "notify_contact_simulated"


class Suspicion(str, Enum):
    DEPRESSION = "depression"
    # ADHD and psychosis modules are optional and require Simula's written permission.


class ModuleOutcome(str, Enum):
    COMPATIBLE = "compatible"
    NOT_COMPATIBLE = "not_compatible"  # never means "ruled out"


class MetricName(str, Enum):
    SLEEP = "sleep"
    CIRCADIAN_RHYTHM = "circadian_rhythm"
    DAYTIME_ACTIVITY = "daytime_activity"
    HEART_RATE = "heart_rate"


# --------------------------------------------------------------------------- #
# Real-time path: SignalBatch -> EpisodeEvent -> QuestionAnswer
# --------------------------------------------------------------------------- #


class Sample(_Contract):
    """One reading from the band. Accelerometer in g, HR in bpm, EDA in µS."""

    t: datetime
    hr: Optional[float] = Field(default=None, ge=20, le=250)
    acc_x: Optional[float] = None
    acc_y: Optional[float] = None
    acc_z: Optional[float] = None
    eda: Optional[float] = Field(default=None, ge=0)

    _tz = field_validator("t")(_require_tz)


class SignalBatch(_Contract):
    """Phone or simulator -> ingest-api. Sent roughly every minute."""

    patient_id: str = Field(pattern=PATIENT_ID_PATTERN)
    device: Device
    sent_at: datetime
    samples: list[Sample] = Field(min_length=1, max_length=20_000)

    _tz = field_validator("sent_at")(_require_tz)

    @model_validator(mode="after")
    def _samples_sorted(self) -> "SignalBatch":
        times = [s.t for s in self.samples]
        if times != sorted(times):
            raise ValueError("samples must be sorted by time")
        return self


class StageTimestamps(_Contract):
    """Per-stage timestamps used to separate network latency from server latency."""

    sample_t: datetime                     # time of the last sample in the window
    ingested_at: Optional[datetime] = None
    inferred_at: Optional[datetime] = None
    pushed_at: Optional[datetime] = None   # question sent to the phone
    received_at: Optional[datetime] = None  # phone confirms reception (optional)

    _tz = field_validator(
        "sample_t", "ingested_at", "inferred_at", "pushed_at", "received_at"
    )(_require_tz)

    def server_latency_ms(self) -> Optional[float]:
        """Ingestion -> inference: the part that depends on LinuxONE."""
        if self.ingested_at and self.inferred_at:
            return (self.inferred_at - self.ingested_at).total_seconds() * 1000
        return None


class EpisodeEvent(_Contract):
    """Detector -> store and phone (WebSocket)."""

    episode_id: str = Field(default_factory=new_episode_id, pattern=EPISODE_ID_PATTERN)
    patient_id: str = Field(pattern=PATIENT_ID_PATTERN)
    start: datetime
    detected_at: datetime
    severity: Severity = Severity.NORMAL
    score: float
    method: DetectionMethod
    features: dict[str, float] = Field(default_factory=dict)  # e.g. hr_z, acc_mag_z, eda_z
    timestamps: StageTimestamps

    _tz = field_validator("start", "detected_at")(_require_tz)


class QuestionAnswer(_Contract):
    """Phone -> store. The patient's in-the-moment answer, linked to its episode."""

    episode_id: str = Field(pattern=EPISODE_ID_PATTERN)
    activity: Optional[Activity] = None
    activity_text: Optional[str] = Field(default=None, max_length=280)
    mood_1_5: Optional[int] = Field(default=None, ge=1, le=5)
    safety_action: Optional[SafetyAction] = None
    answered_at: datetime

    _tz = field_validator("answered_at")(_require_tz)

    @model_validator(mode="after")
    def _not_empty(self) -> "QuestionAnswer":
        if (
            self.activity is None
            and self.mood_1_5 is None
            and self.safety_action is None
            and not self.activity_text
        ):
            raise ValueError("an answer needs at least one field")
        return self


# --------------------------------------------------------------------------- #
# Suspicion module path: ModuleRequest -> ModuleResult
# --------------------------------------------------------------------------- #


class Period(_Contract):
    from_: datetime = Field(alias="from")
    to: datetime

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    _tz = field_validator("from_", "to")(_require_tz)

    @model_validator(mode="after")
    def _ordered(self) -> "Period":
        if self.to <= self.from_:
            raise ValueError("'to' must be after 'from'")
        return self


class ModuleRequest(_Contract):
    """Clinician dashboard -> suspicion-module. Only the requested module runs."""

    patient_id: str = Field(pattern=PATIENT_ID_PATTERN)
    suspicion: Suspicion
    period: Period
    requested_by: str = Field(default="clinician", max_length=64)  # for the audit log


class DataQuality(_Contract):
    valid_days: int = Field(ge=0)
    missing_hours: float = Field(ge=0)


class ReferenceRange(_Contract):
    """Percentiles of the metric in NHANES for the patient's sex and age group."""

    p10: float
    p50: float
    p90: float
    group: str = Field(description="e.g. 'F_30-39'")

    @model_validator(mode="after")
    def _ordered(self) -> "ReferenceRange":
        if not (self.p10 <= self.p50 <= self.p90):
            raise ValueError("percentiles must satisfy p10 <= p50 <= p90")
        return self


class SeriesPoint(_Contract):
    day: str = Field(description="ISO date, e.g. '2026-10-17'")
    value: Optional[float] = None  # None = no valid data that day


class MetricEvidence(_Contract):
    name: MetricName
    unit: str = ""
    patient_series: list[SeriesPoint] = Field(default_factory=list)
    reference: Optional[ReferenceRange] = None  # None when no reference exists (e.g. no HR in NHANES)
    is_evidence: bool = False
    shap: Optional[float] = None
    available: bool = True  # False -> dashboard shows "no data for this metric"


class ModuleResult(_Contract):
    """suspicion-module -> evidence-api -> dashboard. No narrative text, ever."""

    patient_id: str = Field(pattern=PATIENT_ID_PATTERN)
    suspicion: Suspicion
    result: ModuleOutcome
    confidence: float = Field(ge=0, le=1)
    model_version: str
    data_quality: DataQuality
    metrics: list[MetricEvidence] = Field(max_length=4)
    episodes: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)

    _tz = field_validator("generated_at")(_require_tz)

    @field_validator("episodes")
    @classmethod
    def _episode_ids(cls, v: list[str]) -> list[str]:
        import re

        bad = [e for e in v if not re.match(EPISODE_ID_PATTERN, e)]
        if bad:
            raise ValueError(f"invalid episode ids: {bad}")
        return v

    @model_validator(mode="after")
    def _unique_metrics(self) -> "ModuleResult":
        names = [m.name for m in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("each metric may appear only once")
        return self


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #


class AuditEntry(_Contract):
    """Append-only record of every inference (AI Act traceability)."""

    at: datetime = Field(default_factory=utcnow)
    actor: str = Field(max_length=64)   # "detector", "suspicion-module", "clinician", …
    action: str = Field(max_length=64)  # "episode_inference", "module_run", …
    patient_id: str = Field(pattern=PATIENT_ID_PATTERN)
    model_version: Optional[str] = None
    detail: dict[str, str | float | int | bool | None] = Field(default_factory=dict)

    _tz = field_validator("at")(_require_tz)


__all__ = [
    "SCHEMA_VERSION",
    "Activity",
    "AuditEntry",
    "DataQuality",
    "DetectionMethod",
    "Device",
    "EpisodeEvent",
    "MetricEvidence",
    "MetricName",
    "ModuleOutcome",
    "ModuleRequest",
    "ModuleResult",
    "Period",
    "QuestionAnswer",
    "ReferenceRange",
    "SafetyAction",
    "Sample",
    "SeriesPoint",
    "Severity",
    "SignalBatch",
    "StageTimestamps",
    "Suspicion",
    "new_episode_id",
    "new_patient_id",
    "utcnow",
]
