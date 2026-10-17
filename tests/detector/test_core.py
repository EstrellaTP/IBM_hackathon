"""Behaviour of the episode detector on synthetic signals."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from services.common.schemas import DetectionMethod, Sample, Severity
from services.detector.core import (
    DetectorConfig,
    FixedRuleDetector,
    PatientDetector,
    activity_from_sample,
)
from services.detector.settings import load_config

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
PATIENT = "p_0a1b2c3d"


def make_signal(
    seconds: int,
    heart_rate: float,
    activity_g: float = 0.0,
    start: datetime = T0,
    seed: int = 0,
) -> list[Sample]:
    """One sample per second with small noise; activity added on the z axis."""
    rng = random.Random(seed)
    return [
        Sample(
            t=start + timedelta(seconds=i),
            hr=heart_rate + rng.gauss(0, 1.5),
            acc_x=rng.gauss(0, 0.003),
            acc_y=rng.gauss(0, 0.003),
            acc_z=1.0 + activity_g + abs(rng.gauss(0, 0.003)),
            eda=0.4 + rng.gauss(0, 0.01),
        )
        for i in range(seconds)
    ]


def calibrated(config: DetectorConfig | None = None) -> tuple[PatientDetector, datetime]:
    """A detector after 10 calm minutes at 70 bpm, and the time calibration ended."""
    detector = PatientDetector(PATIENT, config or DetectorConfig())
    calm = make_signal(600, heart_rate=70)
    assert detector.process(calm) == []
    assert detector.baseline_ready
    return detector, calm[-1].t + timedelta(seconds=1)


def test_activity_is_zero_at_rest_and_positive_when_moving():
    at_rest = Sample(t=T0, acc_x=0.0, acc_y=0.0, acc_z=1.0)
    moving = Sample(t=T0, acc_x=0.0, acc_y=0.0, acc_z=1.3)
    assert activity_from_sample(at_rest) == 0.0
    assert activity_from_sample(moving) == pytest.approx(0.3)
    assert activity_from_sample(Sample(t=T0, hr=80)) is None


def test_no_episode_during_calm_signal():
    detector, _ = calibrated()
    assert detector.process(make_signal(600, 70, start=T0 + timedelta(minutes=10), seed=1)) == []


def test_no_episode_before_baseline_is_ready():
    detector = PatientDetector(PATIENT)
    assert detector.process(make_signal(120, heart_rate=110)) == []
    assert not detector.baseline_ready


def test_detects_heart_rate_rise_without_movement():
    detector, start = calibrated()
    episodes = detector.process(make_signal(120, heart_rate=95, start=start, seed=2))
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.method == DetectionMethod.ZSCORE
    assert episode.patient_id == PATIENT
    assert episode.features["hr_z"] >= DetectorConfig().hr_z_threshold
    assert episode.timestamps.inferred_at is not None


def test_ignores_heart_rate_explained_by_movement():
    detector, start = calibrated()
    climbing_stairs = make_signal(120, heart_rate=110, activity_g=0.3, start=start, seed=3)
    assert detector.process(climbing_stairs) == []


def test_fixed_rule_fires_on_exercise_where_personal_model_does_not():
    rule = FixedRuleDetector(PATIENT)
    rule.process(make_signal(600, heart_rate=70))
    climbing_stairs = make_signal(
        120, heart_rate=110, activity_g=0.3, start=T0 + timedelta(minutes=10), seed=3
    )
    episodes = rule.process(climbing_stairs)
    assert len(episodes) == 1
    assert episodes[0].method == DetectionMethod.FIXED_RULE


def test_personal_baseline_detects_rise_the_fixed_rule_misses():
    """75 -> 95 bpm is unusual for this person but below the 100 bpm rule."""
    detector, start = calibrated()
    rule = FixedRuleDetector(PATIENT)
    rule.process(make_signal(600, heart_rate=70))
    rise = make_signal(120, heart_rate=95, start=start, seed=4)
    assert len(detector.process(rise)) == 1
    assert rule.process(rise) == []


def test_cooldown_prevents_repeated_questions():
    detector, start = calibrated()
    sustained = make_signal(9 * 60, heart_rate=95, start=start, seed=5)
    assert len(detector.process(sustained)) == 1


def test_asks_again_after_cooldown():
    config = DetectorConfig(cooldown_seconds=120)
    detector, start = calibrated(config)
    sustained = make_signal(6 * 60, heart_rate=95, start=start, seed=6)
    assert len(detector.process(sustained)) >= 2


def test_extreme_rise_triggers_safety_severity():
    detector, start = calibrated()
    episodes = detector.process(make_signal(120, heart_rate=140, start=start, seed=7))
    assert episodes[0].severity == Severity.EXTREME


def test_episode_does_not_contaminate_baseline():
    detector, start = calibrated()
    detector.process(make_signal(300, heart_rate=95, start=start, seed=8))
    baseline_mean = detector._hr_stats.mean
    assert baseline_mean == pytest.approx(70, abs=1.5)


def test_low_quality_windows_are_skipped():
    """After the band loses contact, a few stray readings must not raise a question."""
    detector, start = calibrated()
    after_gap = start + timedelta(minutes=2)
    signal = make_signal(120, 120, start=after_gap, seed=9)
    sparse = [sample for index, sample in enumerate(signal) if index % 20 == 0]
    assert detector.process(sparse) == []


def test_missing_accelerometer_does_not_crash():
    detector, start = calibrated()
    no_acc = [Sample(t=start + timedelta(seconds=i), hr=95 + math.sin(i)) for i in range(120)]
    assert len(detector.process(no_acc)) == 1


def test_load_config_reads_environment():
    config = load_config({"DETECTOR_HR_Z_THRESHOLD": "2.5", "DETECTOR_WARMUP_WINDOWS": "12"})
    assert config.hr_z_threshold == 2.5
    assert config.warmup_windows == 12
    with pytest.raises(ValueError):
        load_config({"DETECTOR_WARMUP_WINDOWS": "many"})
