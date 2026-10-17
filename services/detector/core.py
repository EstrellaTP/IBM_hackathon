"""Real-time episode detection against each patient's personal baseline.

Role in the architecture (CLAUDE.md section 8): ``ingest-api`` forwards every
``SignalBatch`` to the detector. The detector keeps one :class:`PatientDetector`
per patient, slides a window over the incoming samples and emits an
:class:`~services.common.schemas.EpisodeEvent` when the heart rate is unusually
high *for that person* and movement does not explain it. The event is what
triggers the in-the-moment question on the patient's phone.

Method (CLAUDE.md section 10.1, "method A"):

1. Every ``step`` seconds, summarise the last ``window`` seconds of signal into
   three numbers: mean heart rate, mean physical activity and mean EDA.
2. Compare them with the patient's own baseline, kept as an exponentially
   weighted mean and variance that is only updated with calm windows, so an
   episode never contaminates the baseline it is measured against.
3. Flag an episode when the heart-rate z-score is high **and** the activity
   z-score is low (the "movement rule"): a racing heart while climbing stairs is
   exercise, not an episode.
4. Do not ask again during a cool-down period, so the patient is not flooded.

:class:`FixedRuleDetector` implements the naive alternative (``HR > 100 bpm``)
that the demo and the evaluation compare against.

This module is pure Python on purpose: no NumPy or web framework, so it runs
identically on x86 laptops and on big-endian s390x LinuxONE.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from services.common.schemas import (
    DetectionMethod,
    EpisodeEvent,
    Sample,
    Severity,
    StageTimestamps,
    utcnow,
)

logger = logging.getLogger(__name__)

# Standard gravity in g. Activity is measured as the Euclidean norm of the
# acceleration minus 1 g, clipped at zero ("ENMO"), a widely used wrist
# actigraphy metric (van Hees et al., 2013, PLoS ONE 8(4): e61691).
GRAVITY_G = 1.0


@dataclass(frozen=True)
class DetectorConfig:
    """Tunable parameters of the detector.

    Defaults were tuned on real WESAD data in task F1-ML-02 (see DECISIONS.md and
    ``ml/reports/detector_wesad.md``).

    Attributes:
        window_seconds: Length of the signal summarised at each step.
        step_seconds: How often a window is evaluated.
        warmup_windows: Calm windows needed before the baseline is trusted. With
            the defaults, 30 windows x 10 s = 5 minutes of calibration.
        baseline_alpha: Weight of each new calm window in the exponentially
            weighted baseline. 0.02 gives an effective memory of ~50 windows
            (~8 minutes), long enough to ignore short fluctuations.
        hr_z_threshold: Heart-rate z-score above which a window is unusual.
        hr_z_extreme: Heart-rate z-score that switches the question to the
            safety protocol ("Are you OK?").
        activity_z_max: Maximum activity z-score for the heart rate to count as
            *not* explained by movement.
        min_std_hr_bpm: Floor for the heart-rate standard deviation, so a very
            stable baseline does not turn a 2 bpm change into a huge z-score.
        min_std_activity_g: Same floor for activity, in g.
        min_std_eda_us: Same floor for EDA, in microsiemens.
        cooldown_seconds: Minimum time between two questions to the same patient.
        min_samples_per_window: Windows with fewer heart-rate samples are skipped
            as low quality (e.g. the band lost contact).
        movement_lookback_seconds: Movement in this many seconds before the
            window still explains a high heart rate, because heart rate stays up
            for a few minutes after exercise (recovery). 0 checks only the current
            window (v1 behaviour). Tuned on WESAD in F1-ML-02.
        eda_z_min: Minimum EDA z-score for an unusual heart rate to count as an
            episode when EDA is available (stress raises both; HR alone also rises
            with posture or talking). ``-inf`` disables the requirement.
    """

    window_seconds: float = 60.0
    step_seconds: float = 10.0
    warmup_windows: int = 30
    baseline_alpha: float = 0.02
    # The four values below were chosen on real WESAD data with leave-one-subject-out
    # (F1-ML-02, ml/reports/detector_wesad.md): the same values won in 12 of 15 folds.
    # v1 used hr_z_threshold=3.0, activity_z_max=1.0, no look-back and no EDA check.
    hr_z_threshold: float = 2.0
    hr_z_extreme: float = 6.0
    activity_z_max: float = 0.5
    min_std_hr_bpm: float = 2.0
    min_std_activity_g: float = 0.005
    min_std_eda_us: float = 0.05
    cooldown_seconds: float = 600.0
    min_samples_per_window: int = 10
    movement_lookback_seconds: float = 180.0
    eda_z_min: float = 1.0


@dataclass
class WindowSummary:
    """Summary statistics of one window of signal.

    Attributes:
        end: Timestamp of the last sample in the window.
        heart_rate: Mean heart rate in bpm, or ``None`` if no valid samples.
        activity: Mean ENMO activity in g, or ``None`` if no accelerometer data.
        eda: Mean electrodermal activity in microsiemens, or ``None``.
        heart_rate_samples: Number of valid heart-rate samples.
    """

    end: datetime
    heart_rate: float | None
    activity: float | None
    eda: float | None
    heart_rate_samples: int


@dataclass
class _RunningStats:
    """Exponentially weighted mean and variance (West, 1979).

    Used for the personal baseline: recent calm periods weigh more than old ones,
    so the baseline follows slow changes (time of day, medication) without being
    dragged by a single episode.
    """

    alpha: float
    mean: float | None = None
    variance: float = 0.0

    def update(self, value: float) -> None:
        """Add a new observation to the running statistics."""
        if self.mean is None:
            self.mean = value
            return
        delta = value - self.mean
        self.mean += self.alpha * delta
        self.variance = (1 - self.alpha) * (self.variance + self.alpha * delta * delta)

    def z_score(self, value: float, min_std: float) -> float:
        """Return how many standard deviations ``value`` is above the mean."""
        if self.mean is None:
            return 0.0
        std = max(math.sqrt(self.variance), min_std)
        return (value - self.mean) / std


def activity_from_sample(sample: Sample) -> float | None:
    """Return the ENMO activity of one sample in g, or ``None`` if incomplete.

    Args:
        sample: One reading with accelerometer axes in g.

    Returns:
        ``max(0, |acc| - 1 g)``, or ``None`` if any axis is missing.
    """
    if sample.acc_x is None or sample.acc_y is None or sample.acc_z is None:
        return None
    norm = math.sqrt(sample.acc_x**2 + sample.acc_y**2 + sample.acc_z**2)
    return max(0.0, norm - GRAVITY_G)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarise_window(samples: Iterable[Sample]) -> WindowSummary | None:
    """Summarise a window of samples into mean heart rate, activity and EDA.

    Args:
        samples: Samples of one window, sorted by time.

    Returns:
        The window summary, or ``None`` if the window is empty.
    """
    samples = list(samples)
    if not samples:
        return None
    heart_rates = [s.hr for s in samples if s.hr is not None]
    activities = [a for a in (activity_from_sample(s) for s in samples) if a is not None]
    edas = [s.eda for s in samples if s.eda is not None]
    return WindowSummary(
        end=samples[-1].t,
        heart_rate=_mean(heart_rates),
        activity=_mean(activities),
        eda=_mean(edas),
        heart_rate_samples=len(heart_rates),
    )


@dataclass
class PatientDetector:
    """Stateful episode detector for one patient (z-score method).

    Feed it samples in time order with :meth:`process`; it returns the episodes
    detected in those samples. One instance per patient keeps baselines strictly
    personal, which is the core idea of the project.

    Attributes:
        patient_id: Pseudonymous patient id.
        config: Detector parameters.
    """

    patient_id: str
    config: DetectorConfig = field(default_factory=DetectorConfig)
    _buffer: deque[Sample] = field(default_factory=deque, init=False, repr=False)
    _hr_stats: _RunningStats = field(init=False, repr=False)
    _activity_stats: _RunningStats = field(init=False, repr=False)
    _eda_stats: _RunningStats = field(init=False, repr=False)
    _calm_windows: int = field(default=0, init=False)
    _next_evaluation: datetime | None = field(default=None, init=False, repr=False)
    _last_episode_at: datetime | None = field(default=None, init=False, repr=False)
    _recent_activity_z: deque[tuple[datetime, float]] = field(
        default_factory=deque, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Create the three baselines with the configured weight."""
        self._hr_stats = _RunningStats(self.config.baseline_alpha)
        self._activity_stats = _RunningStats(self.config.baseline_alpha)
        self._eda_stats = _RunningStats(self.config.baseline_alpha)

    @property
    def baseline_ready(self) -> bool:
        """Whether enough calm windows have been seen to trust the baseline."""
        return self._calm_windows >= self.config.warmup_windows

    def process(
        self, samples: Iterable[Sample], ingested_at: datetime | None = None
    ) -> list[EpisodeEvent]:
        """Consume new samples and return any episodes they reveal.

        Args:
            samples: New samples for this patient, sorted by time.
            ingested_at: When ``ingest-api`` received the batch; copied into the
                event timestamps to measure server latency.

        Returns:
            Detected episodes, usually zero or one per batch.
        """
        episodes: list[EpisodeEvent] = []
        window = timedelta(seconds=self.config.window_seconds)
        step = timedelta(seconds=self.config.step_seconds)
        for sample in samples:
            self._buffer.append(sample)
            while self._buffer and self._buffer[0].t <= sample.t - window:
                self._buffer.popleft()
            if self._next_evaluation is None:
                # First evaluation once a full window of signal is available.
                self._next_evaluation = sample.t + window
            if sample.t >= self._next_evaluation:
                self._next_evaluation = sample.t + step
                episode = self._evaluate(ingested_at)
                if episode is not None:
                    episodes.append(episode)
        return episodes

    def _evaluate(self, ingested_at: datetime | None) -> EpisodeEvent | None:
        summary = summarise_window(self._buffer)
        if summary is None or summary.heart_rate is None:
            return None
        if summary.heart_rate_samples < self.config.min_samples_per_window:
            logger.debug("patient=%s low-quality window skipped", self.patient_id)
            return None

        cfg = self.config
        hr_z = self._hr_stats.z_score(summary.heart_rate, cfg.min_std_hr_bpm)
        activity_z = (
            self._activity_stats.z_score(summary.activity, cfg.min_std_activity_g)
            if summary.activity is not None
            else 0.0
        )
        eda_z = (
            self._eda_stats.z_score(summary.eda, cfg.min_std_eda_us)
            if summary.eda is not None
            else None
        )

        unusual_heart_rate = hr_z >= cfg.hr_z_threshold
        explained_by_movement = (
            self._recent_max_activity_z(summary.end, activity_z) > cfg.activity_z_max
        )

        if not self.baseline_ready or not unusual_heart_rate:
            # Only calm windows feed the baseline; unusual ones (episodes or
            # exercise) would inflate it and hide the next real episode.
            if not unusual_heart_rate:
                self._update_baseline(summary)
            return None
        if explained_by_movement:
            logger.debug("patient=%s high HR explained by movement", self.patient_id)
            return None
        if eda_z is not None and eda_z < cfg.eda_z_min:
            logger.debug("patient=%s high HR without EDA response", self.patient_id)
            return None
        if self._in_cooldown(summary.end):
            return None

        self._last_episode_at = summary.end
        features = {"hr_z": round(hr_z, 3), "acc_mag_z": round(activity_z, 3)}
        if eda_z is not None:
            features["eda_z"] = round(eda_z, 3)
        event = EpisodeEvent(
            patient_id=self.patient_id,
            start=summary.end - timedelta(seconds=cfg.window_seconds),
            detected_at=utcnow(),
            severity=Severity.EXTREME if hr_z >= cfg.hr_z_extreme else Severity.NORMAL,
            score=round(hr_z, 3),
            method=DetectionMethod.ZSCORE,
            features=features,
            timestamps=StageTimestamps(
                sample_t=summary.end, ingested_at=ingested_at, inferred_at=utcnow()
            ),
        )
        logger.info(
            "patient=%s episode=%s severity=%s",
            self.patient_id,
            event.episode_id,
            event.severity.value,
        )
        return event

    def _recent_max_activity_z(self, now: datetime, activity_z: float) -> float:
        """Record this window's activity z-score and return the recent maximum.

        The maximum covers the current window and every window that ended within
        ``movement_lookback_seconds`` before it.
        """
        lookback = timedelta(seconds=self.config.movement_lookback_seconds)
        self._recent_activity_z.append((now, activity_z))
        while self._recent_activity_z and self._recent_activity_z[0][0] < now - lookback:
            self._recent_activity_z.popleft()
        return max(z for _, z in self._recent_activity_z)

    def _update_baseline(self, summary: WindowSummary) -> None:
        assert summary.heart_rate is not None  # guaranteed by _evaluate
        self._hr_stats.update(summary.heart_rate)
        if summary.activity is not None:
            self._activity_stats.update(summary.activity)
        if summary.eda is not None:
            self._eda_stats.update(summary.eda)
        self._calm_windows += 1

    def _in_cooldown(self, now: datetime) -> bool:
        if self._last_episode_at is None:
            return False
        return now - self._last_episode_at < timedelta(seconds=self.config.cooldown_seconds)


# Heart rate above which the naive rule fires. 100 bpm is the conventional
# upper limit of a normal resting heart rate in adults.
FIXED_RULE_HR_BPM = 100.0


@dataclass
class FixedRuleDetector:
    """Naive baseline for comparison: flag every window with mean HR > 100 bpm.

    It ignores the patient's baseline and movement, which is exactly what the
    demo shows: it fires when climbing stairs, the personal model does not.

    Attributes:
        patient_id: Pseudonymous patient id.
        config: Reuses window, step and cool-down from :class:`DetectorConfig`.
        threshold_bpm: Heart-rate threshold.
    """

    patient_id: str
    config: DetectorConfig = field(default_factory=DetectorConfig)
    threshold_bpm: float = FIXED_RULE_HR_BPM
    _inner: PatientDetector = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Reuse the windowing logic of the personal detector."""
        self._inner = PatientDetector(self.patient_id, self.config)

    def process(
        self, samples: Iterable[Sample], ingested_at: datetime | None = None
    ) -> list[EpisodeEvent]:
        """Return an episode for every window whose mean HR exceeds the threshold.

        Args:
            samples: New samples for this patient, sorted by time.
            ingested_at: When the batch was received, for latency measurement.

        Returns:
            Detected episodes, respecting the same cool-down as the personal model.
        """
        inner = self._inner
        episodes: list[EpisodeEvent] = []
        window = timedelta(seconds=self.config.window_seconds)
        step = timedelta(seconds=self.config.step_seconds)
        for sample in samples:
            inner._buffer.append(sample)
            while inner._buffer and inner._buffer[0].t <= sample.t - window:
                inner._buffer.popleft()
            if inner._next_evaluation is None:
                inner._next_evaluation = sample.t + window
            if sample.t < inner._next_evaluation:
                continue
            inner._next_evaluation = sample.t + step
            summary = summarise_window(inner._buffer)
            if summary is None or summary.heart_rate is None:
                continue
            if summary.heart_rate <= self.threshold_bpm or inner._in_cooldown(summary.end):
                continue
            inner._last_episode_at = summary.end
            episodes.append(
                EpisodeEvent(
                    patient_id=self.patient_id,
                    start=summary.end - window,
                    detected_at=utcnow(),
                    score=round(summary.heart_rate, 1),
                    method=DetectionMethod.FIXED_RULE,
                    features={"hr_mean": round(summary.heart_rate, 1)},
                    timestamps=StageTimestamps(
                        sample_t=summary.end, ingested_at=ingested_at, inferred_at=utcnow()
                    ),
                )
            )
        return episodes
