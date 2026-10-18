"""Common hourly representation for NHANES and DEPRESJON (input of ``circadian``).

Both datasets are reduced to one row per person, recording day and clock hour:
``person_id``, ``day``, ``hour``, ``activity`` (sum over the hour, device units) and
``valid``. Hourly resolution is what the circadian literature uses for IS/IV/L5/M10
and is the finest resolution NHANES provides without the 8.7 GB minute files.
"""

from __future__ import annotations

import pandas as pd

HOURLY_COLUMNS = ["person_id", "day", "hour", "activity", "valid"]

# NHANES hour validity: a full hour (60 minutes measured) with at most 15 minutes of
# non-wear, unknown or quality-flagged data, i.e. >= 75 % wear (a common accelerometry
# threshold for valid periods, e.g. Troiano et al., MSSE 2008, for wear time).
NHANES_MIN_WEAR_MINUTES = 45
NHANES_MAX_FLAGGED_MINUTES = 15
MINUTES_PER_HOUR = 60


def nhanes_hourly(pax_hourly: pd.DataFrame, cycle: str) -> pd.DataFrame:
    """Convert ``loaders.load_nhanes_pax_hourly`` output to the common layout.

    Args:
        pax_hourly: Hourly NHANES rows.
        cycle: Cycle letter, used to build a person id unique across cycles.

    Returns:
        Frame with :data:`HOURLY_COLUMNS`; ``activity`` is the triaxial MIMS sum.
    """
    wear = pax_hourly["wake_wear_min"] + pax_hourly["sleep_wear_min"]
    valid = (
        (pax_hourly["minutes_measured"] == MINUTES_PER_HOUR)
        & (wear >= NHANES_MIN_WEAR_MINUTES)
        & (pax_hourly["quality_flag"] <= NHANES_MAX_FLAGGED_MINUTES)
    )
    return pd.DataFrame(
        {
            "person_id": "nhanes_" + cycle + "_" + pax_hourly["seqn"].astype(str),
            "day": pax_hourly["day"].astype("int64"),
            "hour": (pax_hourly["clock_hour_start_s"] // 3600).astype("int64") % 24,
            "activity": pax_hourly["mims"].astype("float64"),
            "valid": valid,
        }
    )[HOURLY_COLUMNS]


def depresjon_hourly(activity: pd.DataFrame, person_id: str) -> pd.DataFrame:
    """Aggregate DEPRESJON minute counts to clock hours.

    An hour is valid when all 60 minutes are present. DEPRESJON has no non-wear
    detection; long zero runs at night are plausible sleep and are kept.

    Args:
        activity: ``loaders.load_depresjon_activity`` output for one person.
        person_id: ``condition_<n>`` or ``control_<n>``.

    Returns:
        Frame with :data:`HOURLY_COLUMNS`; ``activity`` is the sum of counts.
    """
    stamps = activity["timestamp"]
    first_day = stamps.dt.normalize().min()
    frame = pd.DataFrame(
        {
            "day": (stamps.dt.normalize() - first_day).dt.days + 1,
            "hour": stamps.dt.hour,
            "activity": activity["activity"].astype("float64"),
        }
    )
    grouped = frame.groupby(["day", "hour"], as_index=False).agg(
        activity=("activity", "sum"), minutes=("activity", "size")
    )
    grouped["valid"] = grouped["minutes"] == MINUTES_PER_HOUR
    grouped["person_id"] = person_id
    grouped["day"] = grouped["day"].astype("int64")
    grouped["hour"] = grouped["hour"].astype("int64")
    return grouped[HOURLY_COLUMNS]
