"""Run every loader on the real data and write an aggregate summary (task F0-ML-03).

Runs on the VM, where the data lives::

    python3 -m ml.data.summarize_datasets > ml/reports/datasets_summary.md

The report only contains counts, durations and group-level statistics (no value of
any single participant), so it can be committed as evidence that the datasets load
on LinuxONE.
"""

from __future__ import annotations

import logging
import platform
import sys
import time

import pandas as pd

from ml.data import loaders

logger = logging.getLogger(__name__)


def _table(frame: pd.DataFrame) -> str:
    """Render a small frame as a Markdown table."""
    return frame.to_markdown(index=False, floatfmt=".2f")


def summarize_wesad() -> str:
    """Summarise all WESAD subjects: duration, readings per sensor, label seconds."""
    rows = []
    for subject in loaders.WESAD_SUBJECTS:
        started = time.perf_counter()
        stream = loaders.load_wesad_wrist(subject)
        span = (stream.index[-1] - stream.index[0]).total_seconds()
        acc_rows = stream["acc_x"].dropna()
        seconds = (acc_rows.groupby(stream.loc[acc_rows.index, "condition"]).size()) / 32
        rows.append(
            {
                "subject": subject,
                "minutes": span / 60,
                "hr_readings": int(stream["hr"].count()),
                "eda_readings": int(stream["eda"].count()),
                "acc_readings": int(acc_rows.size),
                "baseline_min": seconds.get("baseline", 0) / 60,
                "stress_min": seconds.get("stress", 0) / 60,
                "amusement_min": seconds.get("amusement", 0) / 60,
                "load_s": time.perf_counter() - started,
            }
        )
        del stream
    frame = pd.DataFrame(rows)
    return "\n".join(
        [
            "## WESAD (wrist, Empatica E4)",
            "",
            f"{len(frame)} subjects. Per-subject recording length and labelled minutes "
            "(no physiological values per person).",
            "",
            _table(frame),
        ]
    )


def summarize_depresjon() -> str:
    """Summarise DEPRESJON: group sizes, recording days and missing minutes."""
    scores = loaders.load_depresjon_scores()
    rows = []
    for person in scores["person_id"]:
        activity = loaders.load_depresjon_activity(person)
        expected = (activity["timestamp"].max() - activity["timestamp"].min()).total_seconds() / 60
        rows.append(
            {
                "person_id": person,
                "minutes": len(activity),
                "gap_minutes": max(0, int(expected) + 1 - len(activity)),
            }
        )
    merged = scores.merge(pd.DataFrame(rows), on="person_id")
    by_group = (
        merged.groupby("group")
        .agg(
            people=("person_id", "count"),
            female=("sex", lambda s: int((s == "F").sum())),
            days_median=("days", "median"),
            recorded_days_median=("minutes", lambda m: m.median() / 1440),
            people_with_gaps=("gap_minutes", lambda g: int((g > 0).sum())),
            madrs_start_mean=("madrs_start", "mean"),
            madrs_end_mean=("madrs_end", "mean"),
        )
        .reset_index()
    )
    types = merged["affective_type"].value_counts().rename_axis("affective_type")
    return "\n".join(
        [
            "## DEPRESJON",
            "",
            _table(by_group),
            "",
            "Affective type among patients:",
            "",
            _table(types.reset_index()),
        ]
    )


def summarize_nhanes() -> str:
    """Summarise NHANES cycle H: participants, PHQ-9 and accelerometry coverage."""
    demographics = loaders.load_nhanes_demographics()
    phq9 = loaders.load_nhanes_phq9()
    header = loaders.load_nhanes_pax_header()
    hourly = loaders.load_nhanes_pax_hourly()
    with_pax = set(hourly["seqn"])
    adults = demographics[demographics["age_years"] >= 18]
    usable = adults.merge(phq9, on="seqn")
    usable = usable[usable["seqn"].isin(with_pax)]
    wear_hours = (
        hourly.assign(worn=hourly["wake_wear_min"] + hourly["sleep_wear_min"])
        .groupby("seqn")["worn"]
        .sum()
        / 60
    )
    usable = usable.assign(wear_hours=usable["seqn"].map(wear_hours))
    usable["age_group"] = pd.cut(
        usable["age_years"],
        bins=[17, 29, 39, 49, 59, 69, 80],
        labels=["18-29", "30-39", "40-49", "50-59", "60-69", "70-80"],
    )
    by_group = (
        usable.groupby(["sex", "age_group"], observed=True)
        .agg(people=("seqn", "count"), phq9_ge_10=("depressive_symptoms", "mean"))
        .reset_index()
    )
    lines = [
        "## NHANES 2013-2014 (cycle H)",
        "",
        f"- Participants in DEMO_H: {len(demographics):,}",
        f"- Complete PHQ-9 questionnaires: {len(phq9):,} "
        f"({phq9['depressive_symptoms'].mean():.1%} with PHQ-9 >= 10, unweighted)",
        f"- Accelerometer header rows: {len(header):,}; with data (PAXSTS = 1): "
        f"{int((header['pax_status'] == 1).sum()):,}",
        f"- Hourly rows: {len(hourly):,} for {hourly['seqn'].nunique():,} people",
        f"- **Adults (18+) with complete PHQ-9 and accelerometry: {len(usable):,}** "
        f"({usable['depressive_symptoms'].mean():.1%} with PHQ-9 >= 10)",
        f"- Worn hours per person (wake + sleep wear): median "
        f"{usable['wear_hours'].median():.0f}, p10 {usable['wear_hours'].quantile(0.1):.0f}",
        "",
        "By sex and age group (unweighted share with PHQ-9 >= 10):",
        "",
        _table(by_group),
    ]
    return "\n".join(lines)


def main() -> int:
    """Print the Markdown report to stdout."""
    logging.basicConfig(level=logging.WARNING)
    sections = [
        "# Datasets loaded on LinuxONE",
        "",
        f"Generated by `python3 -m ml.data.summarize_datasets` on `{platform.machine()}` "
        f"({sys.byteorder}-endian), Python {platform.python_version()}, "
        f"pandas {pd.__version__}.",
        "",
        summarize_wesad(),
        "",
        summarize_depresjon(),
        "",
        summarize_nhanes(),
        "",
    ]
    sys.stdout.write("\n".join(sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
