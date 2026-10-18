"""Suspicion module: from a recording to the clinician's evidence (CLAUDE.md section 5.2).

When the clinician selects a suspicion (only ``depression`` in the prototype), this
module, and only this module, runs over the patient's recording:

1. hourly activity -> per-person features (``ml.features.circadian``) and per-day
   dashboard metrics (``ml.features.daily``);
2. the calibrated, portable model (``ml.models.predict``) gives the probability that
   the pattern is compatible with the suspicion, and per-feature contributions;
3. contributions are summed per dashboard metric; the metrics that push most towards
   the result are marked as evidence;
4. each metric is returned with the patient's daily values and the NHANES reference
   band for their sex and age group, plus the data quality of the recording.

The output is a ``ModuleResult``: numbers, series and flags only. No text is ever
generated about the patient, and "not compatible" never means "ruled out"
(CLAUDE.md section 5.5): that wording lives in the dashboard.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from ml.features import circadian, daily
from ml.models.predict import DepressionModel
from services.common.schemas import (
    DataQuality,
    MetricEvidence,
    MetricName,
    ModuleOutcome,
    ModuleRequest,
    ModuleResult,
    ReferenceRange,
    SeriesPoint,
)

logger = logging.getLogger(__name__)

# Which model features feed each dashboard chart (for marking evidence).
METRIC_FEATURES = {
    MetricName.SLEEP: ["rest_hours_per_day", "night_fragmentation", "l5"],
    MetricName.CIRCADIAN_RHYTHM: ["is_", "iv", "ra", "l5_start_h", "m10_start_h"],
    MetricName.DAYTIME_ACTIVITY: ["daytime_activity", "m10", "sedentary_share", "daily_total_cv"],
}
# At most this many charts are marked as evidence (CLAUDE.md 10.3: the top features).
MAX_EVIDENCE_METRICS = 2
HOURS_PER_DAY = 24
# Same minimum number of valid days as training (ml/features/build.py).
MIN_VALID_DAYS = 4


class InsufficientDataError(ValueError):
    """The recording has too few valid days for the module."""


def reference_group(sex: str, age_group: str) -> str:
    """Map a profile age group ('35-39', '30-39', '70+') to the NHANES band key."""
    first_age = int(age_group[:2])
    if first_age < 30:
        decade = "18-29"
    elif first_age >= 70:
        decade = "70+"
    else:
        start = first_age // 10 * 10
        decade = f"{start}-{start + 9}"
    return f"{sex}_{decade}"


def data_quality(hourly: pd.DataFrame) -> DataQuality:
    """Valid days (>= 20 valid hours) and missing hours over the recorded days."""
    usable = circadian.valid_hours(hourly)
    days = hourly["day"].nunique()
    missing = days * HOURS_PER_DAY - int(hourly["valid"].sum())
    return DataQuality(
        valid_days=int(usable["day"].nunique()), missing_hours=float(max(missing, 0))
    )


def evidence_flags(
    contributions: dict[str, float], compatible: bool
) -> dict[MetricName, tuple[float, bool]]:
    """Sum contributions per metric and flag those pushing most towards the result.

    Args:
        contributions: Per-feature contributions to the log-odds of "compatible".
        compatible: Model outcome.

    Returns:
        ``{metric: (summed contribution, is_evidence)}``.
    """
    sums = {
        metric: sum(contributions.get(feature, 0.0) for feature in features)
        for metric, features in METRIC_FEATURES.items()
    }
    direction = 1.0 if compatible else -1.0
    supporting = sorted(
        (metric for metric, value in sums.items() if value * direction > 0),
        key=lambda metric: -abs(sums[metric]),
    )[:MAX_EVIDENCE_METRICS]
    return {metric: (value, metric in supporting) for metric, value in sums.items()}


class SuspicionModule:
    """Runs the depression module for one patient.

    Args:
        model: Portable calibrated classifier.
        reference_ranges: Content of ``ml/reports/reference_ranges.json``.
    """

    def __init__(self, model: DepressionModel, reference_ranges: dict) -> None:
        self.model = model
        self.reference = reference_ranges

    def run(
        self,
        request: ModuleRequest,
        hourly: pd.DataFrame,
        sex: str,
        age_group: str,
        recording_start: date,
        episode_ids: list[str],
    ) -> ModuleResult:
        """Classify a recording and build the evidence dashboard data.

        Args:
            request: Clinician's request (patient, suspicion, period).
            hourly: ``day``, ``hour``, ``activity``, ``valid`` for the patient.
            sex: ``"F"`` or ``"M"`` (selects the reference band).
            age_group: e.g. ``"35-39"``.
            recording_start: Calendar date of recording day 1.
            episode_ids: Episodes of the patient in the period (shown on the timeline).

        Returns:
            The module result.

        Raises:
            InsufficientDataError: If fewer valid days than the training minimum.
        """
        first = (request.period.from_.date() - recording_start).days + 1
        last = (request.period.to.date() - recording_start).days + 1
        hourly = hourly[(hourly["day"] >= first) & (hourly["day"] <= last)]
        quality = data_quality(hourly)
        if quality.valid_days < MIN_VALID_DAYS:
            raise InsufficientDataError(
                f"{quality.valid_days} valid days; the module needs at least {MIN_VALID_DAYS}"
            )
        features = circadian.person_features(hourly)
        prediction = self.model.predict_raw(features)
        flags = evidence_flags(prediction.contributions, prediction.compatible)
        metrics = self._metrics(hourly, flags, reference_group(sex, age_group), recording_start)
        confidence = prediction.probability if prediction.compatible else 1 - prediction.probability
        logger.info(
            "patient=%s module=%s valid_days=%d",
            request.patient_id,
            request.suspicion.value,
            quality.valid_days,
        )
        return ModuleResult(
            patient_id=request.patient_id,
            suspicion=request.suspicion,
            result=ModuleOutcome.COMPATIBLE
            if prediction.compatible
            else ModuleOutcome.NOT_COMPATIBLE,
            confidence=round(confidence, 3),
            model_version=self.model.version,
            data_quality=quality,
            metrics=metrics,
            episodes=episode_ids,
        )

    def _metrics(
        self,
        hourly: pd.DataFrame,
        flags: dict[MetricName, tuple[float, bool]],
        group: str,
        recording_start: date,
    ) -> list[MetricEvidence]:
        days = daily.daily_metrics(hourly)
        metrics = []
        for name in (MetricName.SLEEP, MetricName.CIRCADIAN_RHYTHM, MetricName.DAYTIME_ACTIVITY):
            band = self.reference["ranges"].get(name.value, {}).get(group)
            series = [
                SeriesPoint(
                    day=(recording_start + timedelta(days=int(row["day"]) - 1)).isoformat(),
                    value=None if pd.isna(row[name.value]) else round(float(row[name.value]), 3),
                )
                for _, row in days.iterrows()
            ]
            contribution, is_evidence = flags[name]
            metrics.append(
                MetricEvidence(
                    name=name,
                    unit=daily.METRIC_UNITS[name.value],
                    patient_series=series,
                    reference=ReferenceRange(
                        p10=band["p10"], p50=band["p50"], p90=band["p90"], group=group
                    )
                    if band
                    else None,
                    is_evidence=is_evidence,
                    shap=round(contribution, 4),
                )
            )
        # No heart rate in the actigraphy recordings or in NHANES: shown as "no data".
        metrics.append(MetricEvidence(name=MetricName.HEART_RATE, unit="bpm", available=False))
        return metrics
