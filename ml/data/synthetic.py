"""Synthetic data with exactly the layout of :mod:`ml.data.loaders` (task F0-ML-02).

Used by tests and by the [APP] lane, which has no access to the real datasets. The
values are plausible but invented: no real person is behind any row. Every function
takes a ``seed`` so results are reproducible.

Shapes produced:

* :func:`wesad_wrist_stream` - like :func:`ml.data.loaders.load_wesad_wrist`: ACC at
  32 Hz in g, HR at 1 Hz, EDA at 4 Hz, with a calm baseline, a stress period (HR and
  EDA up while sitting still) and an exercise period (HR up with movement).
* :func:`depresjon_activity` - like :func:`ml.data.loaders.load_depresjon_activity`:
  minute counts with a day/night rhythm, flatter and lower when ``depressed``.
* :func:`nhanes_tables` - demographics, PHQ-9 and hourly MIMS tables like the NHANES
  loaders, with a weak link between lower daytime activity and PHQ-9 >= 10.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.data import loaders

# Typical resting values for a healthy adult, used as the synthetic baseline.
REST_HEART_RATE_BPM = 70.0
REST_EDA_MICROSIEMENS = 0.4
STRESS_HEART_RATE_INCREASE_BPM = 25.0
EXERCISE_HEART_RATE_INCREASE_BPM = 45.0


@dataclass(frozen=True)
class Period:
    """A labelled period of a synthetic WESAD-like recording, in seconds from start."""

    start_s: int
    end_s: int
    condition: str  # "stress" or "exercise"


DEFAULT_PERIODS = (Period(1200, 1800, "stress"), Period(2400, 2700, "exercise"))


def wesad_wrist_stream(
    duration_s: int = 3600,
    periods: tuple[Period, ...] = DEFAULT_PERIODS,
    start: str = "2026-01-01T09:00:00Z",
    seed: int = 0,
) -> pd.DataFrame:
    """Generate a wrist stream with the columns of ``load_wesad_wrist``.

    Exercise is labelled ``amusement`` (code 3) because WESAD has no exercise label;
    it only serves to test that movement-explained HR is ignored.

    Args:
        duration_s: Length of the recording in seconds.
        periods: Stress / exercise periods.
        start: UTC start time.
        seed: Random seed.

    Returns:
        Frame indexed by UTC ``t`` with :data:`ml.data.loaders.WESAD_WRIST_COLUMNS`.
    """
    rng = np.random.default_rng(seed)
    acc_t = np.arange(duration_s * loaders.E4_ACC_HZ) / loaders.E4_ACC_HZ
    hr_t = np.arange(duration_s, dtype=np.float64)
    eda_t = np.arange(duration_s * 4) / 4

    def _mask(times: np.ndarray, condition: str) -> np.ndarray:
        inside = np.zeros(len(times), dtype=bool)
        for period in periods:
            if period.condition == condition:
                inside |= (times >= period.start_s) & (times < period.end_s)
        return inside

    # Gravity on z plus small noise; exercise adds a 2 Hz swing of about 0.5 g.
    acc = np.column_stack(
        [rng.normal(0, 0.02, len(acc_t)), rng.normal(0, 0.02, len(acc_t)), np.ones(len(acc_t))]
    )
    acc[:, 2] += rng.normal(0, 0.02, len(acc_t))
    moving = _mask(acc_t, "exercise")
    acc[moving, 0] += 0.5 * np.sin(2 * np.pi * 2.0 * acc_t[moving])

    hr = REST_HEART_RATE_BPM + rng.normal(0, 2.0, len(hr_t))
    hr[_mask(hr_t, "stress")] += STRESS_HEART_RATE_INCREASE_BPM
    hr[_mask(hr_t, "exercise")] += EXERCISE_HEART_RATE_INCREASE_BPM
    eda = REST_EDA_MICROSIEMENS + np.abs(rng.normal(0, 0.02, len(eda_t)))
    eda[_mask(eda_t, "stress")] += 0.6

    frames = [
        pd.DataFrame({"t": acc_t, "acc_x": acc[:, 0], "acc_y": acc[:, 1], "acc_z": acc[:, 2]}),
        pd.DataFrame({"t": hr_t, "hr": hr}),
        pd.DataFrame({"t": eda_t, "eda": eda}),
    ]
    stream = pd.concat(frames, ignore_index=True).groupby("t", sort=True).first()
    times = stream.index.to_numpy()
    label = np.ones(len(stream), dtype=np.int64)  # baseline
    label[_mask(times, "stress")] = 2
    label[_mask(times, "exercise")] = 3
    stream["label"] = label
    stream["condition"] = stream["label"].map(loaders.WESAD_CONDITIONS)
    stream.index = pd.Timestamp(start) + pd.to_timedelta(times, unit="s")
    stream.index.name = "t"
    return stream[loaders.WESAD_WRIST_COLUMNS]


def depresjon_activity(
    days: int = 7, depressed: bool = False, start: str = "2026-01-05 00:00", seed: int = 0
) -> pd.DataFrame:
    """Generate minute activity counts with the columns of ``load_depresjon_activity``.

    Activity follows a day/night cycle (active roughly 08:00-23:00). The
    ``depressed`` profile has lower and more irregular daytime activity, matching
    the direction reported for DEPRESJON (Garcia-Ceja et al. 2018).

    Args:
        days: Number of full days.
        depressed: Use the low-activity profile.
        start: Naive local start time, like the dataset.
        seed: Random seed.

    Returns:
        Frame with :data:`ml.data.loaders.DEPRESJON_ACTIVITY_COLUMNS`.
    """
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range(start, periods=days * 1440, freq="min")
    hour = timestamps.hour.to_numpy() + timestamps.minute.to_numpy() / 60
    awake = (hour >= 8) & (hour < 23)
    day_mean = 150.0 if depressed else 300.0
    mean = np.where(awake, day_mean, 5.0)
    if depressed:
        mean = mean * rng.uniform(0.5, 1.5, len(mean))  # irregular rhythm
    activity = rng.poisson(mean).astype(np.int64)
    return pd.DataFrame({"timestamp": timestamps, "activity": activity})


def nhanes_tables(
    people: int = 200, days: int = 7, seed: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate NHANES-like demographics, PHQ-9 and hourly activity tables.

    Args:
        people: Number of synthetic participants.
        days: Recording days per participant (24 rows each).
        seed: Random seed.

    Returns:
        ``(demographics, phq9, pax_hourly)`` with the loaders' column lists.
    """
    rng = np.random.default_rng(seed)
    seqn = np.arange(1, people + 1, dtype=np.int64)
    demographics = pd.DataFrame(
        {
            "seqn": seqn,
            "sex": rng.choice(["F", "M"], people),
            "age_years": rng.integers(18, 81, people).astype(np.float64),
            "exam_weight": rng.uniform(5_000, 50_000, people),
        }
    )[loaders.DEMOGRAPHICS_COLUMNS]

    # About 10 % with PHQ-9 >= 10, close to the real NHANES 2013-2014 share (9.5 %).
    phq9_total = np.clip(rng.negative_binomial(1, 0.25, people), 0, 27).astype(np.int64)
    phq9 = pd.DataFrame(
        {
            "seqn": seqn,
            "phq9_total": phq9_total,
            "depressive_symptoms": phq9_total >= loaders.PHQ9_SYMPTOMS_CUTOFF,
        }
    )[loaders.PHQ9_COLUMNS]

    rows = []
    for person, total in zip(seqn, phq9_total, strict=True):
        activity_scale = 1.0 - 0.02 * total  # weak, invented link for tests only
        for day in range(1, days + 1):
            for hour in range(24):
                awake = 8 <= hour < 23
                mims = rng.gamma(4.0, (300.0 if awake else 20.0) * activity_scale / 4.0)
                rows.append(
                    (person, day, (day % 7) + 1, hour * 3600, 60.0, mims, 60.0 if awake else 0.0,
                     0.0 if awake else 60.0, 0.0, 0.0, 0.0)
                )  # fmt: skip
    pax_hourly = pd.DataFrame(rows, columns=loaders.PAX_HOURLY_COLUMNS)
    return demographics, phq9, pax_hourly
