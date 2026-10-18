"""Age- and sex-specific reference ranges for the dashboard metrics (task F2-ML-02).

Runs on the VM::

    python3 -m ml.models.reference_ranges --out ml/reports/reference_ranges.json

For every NHANES G+H adult with >= 4 valid days, each daily metric of
``ml.features.daily`` is summarised by its median over the person's days. The p10,
p50 and p90 of those person medians are computed per sex and age group, **weighted by
the NHANES examination weight** (``WTMEC2YR``) so the bands describe the US adult
population rather than the sample. The JSON matches ``ReferenceRange`` in
``services/common/schemas.py`` (``group`` like ``"F_30-39"``) and only contains
aggregate statistics, so it is committed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data import loaders
from ml.features import daily, hourly
from ml.features.build import ADULT_AGE_YEARS, MIN_VALID_DAYS

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
AGE_BINS = [17, 29, 39, 49, 59, 69, 120]
AGE_LABELS = ["18-29", "30-39", "40-49", "50-59", "60-69", "70+"]
PERCENTILES = (10, 50, 90)


def weighted_percentile(values: np.ndarray, weights: np.ndarray, percent: float) -> float:
    """Weighted percentile (linear interpolation of the weighted empirical CDF)."""
    mask = ~np.isnan(values)
    values, weights = values[mask], weights[mask]
    if len(values) == 0:
        return float("nan")
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    cumulative = (np.cumsum(weights) - 0.5 * weights) / weights.sum()
    return float(np.interp(percent / 100, cumulative, values))


def person_medians(cycle: str) -> pd.DataFrame:
    """Median of each daily metric per NHANES adult, with sex, age and weight."""
    demographics = loaders.load_nhanes_demographics(cycle)
    adults = demographics[demographics["age_years"] >= ADULT_AGE_YEARS]
    pax = loaders.load_nhanes_pax_hourly(cycle)
    pax = pax[pax["seqn"].isin(adults["seqn"])]
    rows = []
    for person_id, person in hourly.nhanes_hourly(pax, cycle).groupby("person_id", sort=False):
        days = daily.daily_metrics(person)
        if len(days) < MIN_VALID_DAYS:
            continue
        rows.append({"person_id": person_id, **days[daily.DAILY_METRICS].median().to_dict()})
    medians = pd.DataFrame(rows)
    adults = adults.assign(person_id="nhanes_" + cycle + "_" + adults["seqn"].astype(str))
    return adults.merge(medians, on="person_id")


def reference_ranges(people: pd.DataFrame) -> dict:
    """p10/p50/p90 per metric and sex x age group, weighted by exam weight."""
    people = people.assign(
        age_group=pd.cut(people["age_years"], AGE_BINS, labels=AGE_LABELS).astype(str)
    )
    ranges: dict[str, dict] = {metric: {} for metric in daily.DAILY_METRICS}
    for (sex, age_group), group in people.groupby(["sex", "age_group"]):
        weights = group["exam_weight"].to_numpy(dtype=float)
        for metric in daily.DAILY_METRICS:
            values = group[metric].to_numpy(dtype=float)
            p10, p50, p90 = (weighted_percentile(values, weights, q) for q in PERCENTILES)
            ranges[metric][f"{sex}_{age_group}"] = {
                "p10": round(p10, 4),
                "p50": round(p50, 4),
                "p90": round(p90, 4),
                "group": f"{sex}_{age_group}",
                "people": int(len(group)),
            }
    return {
        "source": "NHANES 2011-2014 (cycles G and H), adults with >= 4 valid days",
        "weighting": "NHANES examination weight WTMEC2YR",
        "units": daily.METRIC_UNITS,
        "heart_rate": None,
        "ranges": ranges,
    }


def main(argv: list[str] | None = None) -> int:
    """Compute and write the reference ranges."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="NHANES reference ranges for the dashboard.")
    parser.add_argument("--out", type=Path, default=REPORTS_DIR / "reference_ranges.json")
    args = parser.parse_args(argv)
    people = pd.concat([person_medians(cycle) for cycle in ("G", "H")], ignore_index=True)
    result = reference_ranges(people)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    logger.info("%d people -> %s", len(people), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
