"""Detector v2: per-patient Isolation Forest (CLAUDE.md section 10.1, "method B").

Same interface as :class:`services.detector.core.PatientDetector` (``process(samples)``
returns ``EpisodeEvent`` objects) so ``ml.models.detector_evaluation`` can compare it
with the z-score detector and the fixed rule on the same replayed data.

Per patient:

1. Windows are summarised exactly like the z-score detector (mean HR, mean ENMO
   activity, mean EDA over ``window_seconds`` every ``step_seconds``).
2. The first ``calibration_windows`` windows train an Isolation Forest (Liu, Ting and
   Zhou, ICDM 2008) on ``[hr, activity, eda]`` standardised with the calibration
   mean and SD.
3. A later window is an episode when its anomaly score exceeds ``score_threshold``,
   the heart rate is above the calibration mean (anomalies caused by a *low* heart
   rate are not what the question is for), recent movement does not explain it
   (same look-back rule as the z-score detector) and the cool-down has passed.

Kept in ``ml/`` for evaluation only: deploying it would add scikit-learn to the
detector image, and the z-score detector is what runs in the real-time path.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from sklearn.ensemble import IsolationForest

from services.common.schemas import (
    DetectionMethod,
    EpisodeEvent,
    Sample,
    StageTimestamps,
    utcnow,
)
from services.detector.core import summarise_window

# Scores from IsolationForest.score_samples are negated so that higher means more
# anomalous; typical values are ~0.4-0.5 for normal points and > 0.6 for outliers.
DEFAULT_SCORE_THRESHOLD = 0.6
# Smallest SD used to standardise features (avoids division by ~0 on flat signals).
MIN_FEATURE_STD = 1e-3


@dataclass(frozen=True)
class IsolationForestConfig:
    """Parameters of the Isolation Forest detector."""

    window_seconds: float = 60.0
    step_seconds: float = 10.0
    calibration_windows: int = 60
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    activity_z_max: float = 0.5
    movement_lookback_seconds: float = 180.0
    cooldown_seconds: float = 600.0
    min_samples_per_window: int = 10
    n_estimators: int = 100
    random_state: int = 0


@dataclass
class IsolationForestDetector:
    """Stateful Isolation Forest detector for one patient."""

    patient_id: str
    config: IsolationForestConfig = field(default_factory=IsolationForestConfig)
    _buffer: deque[Sample] = field(default_factory=deque, init=False, repr=False)
    _calibration: list[list[float]] = field(default_factory=list, init=False, repr=False)
    _model: IsolationForest | None = field(default=None, init=False, repr=False)
    _mean: np.ndarray | None = field(default=None, init=False, repr=False)
    _std: np.ndarray | None = field(default=None, init=False, repr=False)
    _next_evaluation: datetime | None = field(default=None, init=False, repr=False)
    _last_episode_at: datetime | None = field(default=None, init=False, repr=False)
    _recent_activity_z: deque[tuple[datetime, float]] = field(
        default_factory=deque, init=False, repr=False
    )

    def process(self, samples: Iterable[Sample]) -> list[EpisodeEvent]:
        """Consume samples in time order and return the episodes found."""
        episodes = []
        window = timedelta(seconds=self.config.window_seconds)
        step = timedelta(seconds=self.config.step_seconds)
        for sample in samples:
            self._buffer.append(sample)
            while self._buffer and self._buffer[0].t <= sample.t - window:
                self._buffer.popleft()
            if self._next_evaluation is None:
                self._next_evaluation = sample.t + window
            if sample.t >= self._next_evaluation:
                self._next_evaluation = sample.t + step
                episode = self._evaluate()
                if episode is not None:
                    episodes.append(episode)
        return episodes

    def _evaluate(self) -> EpisodeEvent | None:
        cfg = self.config
        summary = summarise_window(self._buffer)
        if summary is None or summary.heart_rate is None:
            return None
        if summary.heart_rate_samples < cfg.min_samples_per_window:
            return None
        vector = [summary.heart_rate, summary.activity or 0.0, summary.eda or 0.0]
        if self._model is None:
            self._calibration.append(vector)
            if len(self._calibration) >= cfg.calibration_windows:
                self._fit()
            return None
        x = (np.asarray(vector) - self._mean) / self._std
        score = float(-self._model.score_samples(x.reshape(1, -1))[0])
        activity_z = float(x[1])
        lookback = timedelta(seconds=cfg.movement_lookback_seconds)
        self._recent_activity_z.append((summary.end, activity_z))
        while self._recent_activity_z[0][0] < summary.end - lookback:
            self._recent_activity_z.popleft()
        moving = max(z for _, z in self._recent_activity_z) > cfg.activity_z_max
        if score < cfg.score_threshold or x[0] <= 0 or moving or self._in_cooldown(summary.end):
            return None
        self._last_episode_at = summary.end
        return EpisodeEvent(
            patient_id=self.patient_id,
            start=summary.end - timedelta(seconds=cfg.window_seconds),
            detected_at=utcnow(),
            score=round(score, 4),
            method=DetectionMethod.IFOREST,
            features={"hr_z": round(float(x[0]), 3), "acc_mag_z": round(activity_z, 3)},
            timestamps=StageTimestamps(sample_t=summary.end, inferred_at=utcnow()),
        )

    def _fit(self) -> None:
        data = np.asarray(self._calibration)
        self._mean = data.mean(axis=0)
        self._std = np.maximum(data.std(axis=0), MIN_FEATURE_STD)
        self._model = IsolationForest(
            n_estimators=self.config.n_estimators, random_state=self.config.random_state
        ).fit((data - self._mean) / self._std)

    def _in_cooldown(self, now: datetime) -> bool:
        if self._last_episode_at is None:
            return False
        return now - self._last_episode_at < timedelta(seconds=self.config.cooldown_seconds)
