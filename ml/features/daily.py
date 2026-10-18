"""Daily dashboard metrics, comparable across devices (sleep, rhythm, daytime activity).

The evidence dashboard shows one chart per metric with the patient's value for each
day against an age- and sex-specific reference band (CLAUDE.md section 5.2). NHANES
(MIMS) and a clinical band (counts) have different units, so the three metrics are
**scale-free**, defined relative to the person's own active level (M10):

* ``sleep``: hours of the day with activity below 0.1·M10 (rest/sleep proxy, hours).
* ``circadian_rhythm``: relative amplitude of that day, (M10 − L5) / (M10 + L5), 0–1.
* ``daytime_activity``: mean activity of 08:00–22:00 divided by the person's M10
  (typical active level), so about 1 on a usually active day and lower on a
  slower one. A first version counted hours above 0.25·M10 and saturated at 1
  for most NHANES adults (p50 0.93–0.96), which made the chart uninformative.

``heart_rate`` has no reference: NHANES does not record it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.features import circadian

DAILY_METRICS = ["sleep", "circadian_rhythm", "daytime_activity"]
DAILY_COLUMNS = ["day", *DAILY_METRICS]
METRIC_UNITS = {"sleep": "h/day", "circadian_rhythm": "0-1", "daytime_activity": "x own M10"}


def _day_relative_amplitude(day: pd.DataFrame) -> float:
    profile = day.set_index("hour")["activity"].reindex(range(24)).to_numpy(dtype=float)
    l5, _ = circadian.window_extreme(profile, circadian.L5_HOURS, lowest=True)
    m10, _ = circadian.window_extreme(profile, circadian.M10_HOURS, lowest=False)
    return (m10 - l5) / (m10 + l5) if (m10 + l5) > 0 else np.nan


def daily_metrics(hourly: pd.DataFrame) -> pd.DataFrame:
    """Per-day dashboard metrics for one person.

    Args:
        hourly: ``day``, ``hour``, ``activity``, ``valid`` (``ml.features.hourly`` layout).

    Returns:
        One row per valid day with :data:`DAILY_COLUMNS` (empty if no valid day).
    """
    usable = circadian.valid_hours(hourly)
    if usable.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    m10, _ = circadian.window_extreme(
        circadian.profile_24h(usable), circadian.M10_HOURS, lowest=False
    )
    rows = []
    for day, group in usable.groupby("day"):
        daytime = group[
            (group["hour"] >= circadian.DAY_START_HOUR) & (group["hour"] < circadian.DAY_END_HOUR)
        ]
        rows.append(
            {
                "day": int(day),
                "sleep": float((group["activity"] < circadian.REST_FRACTION_OF_M10 * m10).sum()),
                "circadian_rhythm": float(_day_relative_amplitude(group)),
                "daytime_activity": float(daytime["activity"].mean() / m10)
                if len(daytime) and m10 > 0
                else np.nan,
            }
        )
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)
