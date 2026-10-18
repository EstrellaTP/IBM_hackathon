"""Non-parametric circadian and activity features from an hourly activity series.

Input for one person: a frame with ``day`` (recording day), ``hour`` (clock hour
0-23), ``activity`` (sum of activity in that hour, any device unit) and ``valid``
(enough wear time). Every function ignores invalid hours.

Features (formulas and references in ``ml/features/README.md``):

* ``is_`` interdaily stability and ``iv`` intradaily variability (Witting et al.,
  Biol Psychiatry 1990; van Someren et al., Chronobiol Int 1999).
* ``l5``/``m10``: mean activity of the least active 5 and most active 10 consecutive
  hours of the average 24-h profile, with their start hours; ``ra`` relative
  amplitude = (M10 - L5) / (M10 + L5) (van Someren et al., 1999).
* Device-independent activity features relative to the person's own M10, so they
  transfer between NHANES (MIMS) and DEPRESJON (Actiwatch counts): rest hours per
  day, night fragmentation, sedentary share and day-to-day variability.

IS, IV, RA, the shares and timings are scale-free. L5, M10 and daytime activity keep
device units and must be standardised within each dataset before pooling.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

HOURS_PER_DAY = 24
L5_HOURS = 5
M10_HOURS = 10

# An hour counts as "rest" when its activity is below this fraction of the person's
# M10 (their typical active level). Relative, so it works across device units.
REST_FRACTION_OF_M10 = 0.1

# "Sedentary" hour: below this fraction of M10 while awake-time hours (08-22).
SEDENTARY_FRACTION_OF_M10 = 0.25

# Daytime used for daytime activity and sedentary share (clock hours, inclusive start).
DAY_START_HOUR = 8
DAY_END_HOUR = 22

# Night window for fragmentation: 8 hours centred on the middle of L5.
NIGHT_WINDOW_HOURS = 8

# A day is analysed when at least this many of its 24 hours are valid.
MIN_VALID_HOURS_PER_DAY = 20

FEATURE_COLUMNS = [
    "is_",
    "iv",
    "ra",
    "l5",
    "m10",
    "l5_start_h",
    "m10_start_h",
    "daytime_activity",
    "rest_hours_per_day",
    "night_fragmentation",
    "sedentary_share",
    "daily_total_cv",
    "valid_days",
]

# Features that keep device units (standardise within dataset before pooling).
DEVICE_SCALED_FEATURES = ["l5", "m10", "daytime_activity"]


def valid_hours(hourly: pd.DataFrame) -> pd.DataFrame:
    """Keep valid hours of days with at least :data:`MIN_VALID_HOURS_PER_DAY` of them."""
    valid = hourly[hourly["valid"]]
    counts = valid.groupby("day")["hour"].transform("count")
    return valid[counts >= MIN_VALID_HOURS_PER_DAY]


def profile_24h(hourly: pd.DataFrame) -> np.ndarray:
    """Average activity for each clock hour 0-23 (``NaN`` where no valid hour)."""
    means = hourly.groupby("hour")["activity"].mean()
    return means.reindex(range(HOURS_PER_DAY)).to_numpy(dtype=float)


def interdaily_stability(hourly: pd.DataFrame) -> float:
    """IS = N·Σ_h(x̄_h − x̄)² / (p·Σ_i(x_i − x̄)²), p = 24 (Witting et al. 1990).

    0 for no day-to-day regularity, 1 when every day repeats the same profile.
    """
    values = hourly["activity"].to_numpy(dtype=float)
    total_variance = np.sum((values - values.mean()) ** 2)
    if len(values) < 2 or total_variance == 0:
        return math.nan
    hour_means = hourly.groupby("hour")["activity"].mean()
    between = np.sum((hour_means - values.mean()) ** 2)
    return float(len(values) * between / (len(hour_means) * total_variance))


def intradaily_variability(hourly: pd.DataFrame) -> float:
    """IV = N·Σ(x_i − x_{i−1})² / ((N−1)·Σ(x_i − x̄)²) over consecutive valid hours.

    Near 0 for a smooth rhythm, around 2 for noise: higher means a more fragmented
    rhythm (Witting et al. 1990). Only pairs of hours that are truly consecutive
    (same or next day, no gap) contribute to the numerator.
    """
    ordered = hourly.sort_values(["day", "hour"])
    values = ordered["activity"].to_numpy(dtype=float)
    position = ordered["day"].to_numpy() * HOURS_PER_DAY + ordered["hour"].to_numpy()
    total_variance = np.sum((values - values.mean()) ** 2)
    consecutive = np.diff(position) == 1
    if consecutive.sum() < 2 or total_variance == 0:
        return math.nan
    # With gaps, Σ(x_i − x_{i−1})² over N−1 pairs is estimated as (N−1)·mean of the
    # truly consecutive squared steps; the (N−1) factors then cancel.
    mean_squared_step = np.mean(np.diff(values)[consecutive] ** 2)
    return float(len(values) * mean_squared_step / total_variance)


def window_extreme(profile: np.ndarray, width: int, lowest: bool) -> tuple[float, int]:
    """Mean and start hour of the least (or most) active circular window of the profile.

    Args:
        profile: 24 hourly means (``NaN`` allowed, ignored within a window).
        width: Window length in hours.
        lowest: Find the least active window (L5) instead of the most active (M10).

    Returns:
        ``(mean activity, start hour)``.
    """
    extended = np.concatenate([profile, profile[: width - 1]])
    means = np.array([np.nanmean(extended[h : h + width]) for h in range(HOURS_PER_DAY)])
    index = int(np.nanargmin(means) if lowest else np.nanargmax(means))
    return float(means[index]), index


def person_features(hourly: pd.DataFrame) -> dict[str, float]:
    """Compute :data:`FEATURE_COLUMNS` for one person's hourly series.

    Args:
        hourly: ``day``, ``hour``, ``activity``, ``valid`` for one person.

    Returns:
        Feature dictionary; values are ``NaN`` when there are no valid days.
    """
    usable = valid_hours(hourly)
    valid_days = int(usable["day"].nunique())
    if valid_days == 0:
        return {name: math.nan for name in FEATURE_COLUMNS} | {"valid_days": 0}
    profile = profile_24h(usable)
    l5, l5_start = window_extreme(profile, L5_HOURS, lowest=True)
    m10, m10_start = window_extreme(profile, M10_HOURS, lowest=False)
    ra = (m10 - l5) / (m10 + l5) if (m10 + l5) > 0 else math.nan

    rest = usable["activity"] < REST_FRACTION_OF_M10 * m10
    rest_hours_per_day = float(rest.groupby(usable["day"]).sum().mean())

    night_fragmentation = _night_fragmentation(usable, l5_start, REST_FRACTION_OF_M10 * m10)

    daytime = usable[(usable["hour"] >= DAY_START_HOUR) & (usable["hour"] < DAY_END_HOUR)]
    daytime_activity = float(daytime["activity"].mean()) if len(daytime) else math.nan
    sedentary_share = (
        float((daytime["activity"] < SEDENTARY_FRACTION_OF_M10 * m10).mean())
        if len(daytime)
        else math.nan
    )
    daily_totals = usable.groupby("day")["activity"].sum()
    daily_total_cv = (
        float(daily_totals.std(ddof=0) / daily_totals.mean())
        if daily_totals.mean() > 0 and valid_days > 1
        else math.nan
    )
    return {
        "is_": interdaily_stability(usable),
        "iv": intradaily_variability(usable),
        "ra": ra,
        "l5": l5,
        "m10": m10,
        "l5_start_h": float(l5_start),
        "m10_start_h": float(m10_start),
        "daytime_activity": daytime_activity,
        "rest_hours_per_day": rest_hours_per_day,
        "night_fragmentation": night_fragmentation,
        "sedentary_share": sedentary_share,
        "daily_total_cv": daily_total_cv,
        "valid_days": valid_days,
    }


def _night_fragmentation(usable: pd.DataFrame, l5_start: int, rest_threshold: float) -> float:
    """Mean number of rest -> active transitions per night.

    The night is the :data:`NIGHT_WINDOW_HOURS` window centred on the middle of L5.
    Hours before the window start belong to the previous night, so a night that
    crosses midnight is counted once.
    """
    centre = (l5_start + L5_HOURS / 2) % HOURS_PER_DAY
    window_start = (centre - NIGHT_WINDOW_HOURS / 2) % HOURS_PER_DAY
    offsets = (usable["hour"] - window_start) % HOURS_PER_DAY
    night = usable[offsets < NIGHT_WINDOW_HOURS].copy()
    if night.empty:
        return math.nan
    night["night"] = night["day"] - (night["hour"] < window_start).astype(int)
    night = night.sort_values(["night", "day", "hour"])
    night["rest"] = night["activity"] < rest_threshold
    awakenings = night.groupby("night")["rest"].apply(
        lambda rest: int((rest.astype(int).diff() == -1).sum())
    )
    return float(awakenings.mean())


def standardise_within_dataset(features: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Log-transform and z-score device-scaled columns within one dataset.

    Activity sums are right-skewed and their units differ between devices, so
    ``log1p`` then z-scoring within the dataset makes them comparable across
    NHANES and DEPRESJON (CLAUDE.md section 10.2, "normalización").
    """
    result = features.copy()
    for column in columns:
        logged = np.log1p(result[column].clip(lower=0))
        std = logged.std(ddof=0)
        result[column] = (logged - logged.mean()) / std if std > 0 else 0.0
    return result
