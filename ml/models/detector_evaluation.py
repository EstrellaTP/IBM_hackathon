"""Tune and evaluate the episode detector on real WESAD data (task F1-ML-02).

Question answered: with real wrist signals, how often does the personal-baseline
detector catch the stress period, how many false alarms does it raise per hour of
non-stress signal, and how does it compare with the fixed ``HR > 100`` rule?

Protocol (no tuning on the evaluated subject):

1. Each WESAD subject's wrist stream is replayed through the detector for every
   configuration of a small grid.
2. **Leave-one-subject-out:** for each subject, the configuration with the best
   pooled event F1 on the *other* 14 subjects is chosen and its result on the
   held-out subject is kept. The reported metrics are those held-out results.
3. The default configuration and the fixed rule are reported on all subjects.

Event definitions:

* Stress event: a contiguous run of WESAD label 2 (the Trier Social Stress Test).
* True detection: an episode whose detection instant (end of its window) falls
  inside a stress event or up to ``STRESS_GRACE_SECONDS`` after it.
* False alarm: any other episode. Non-stress time includes baseline, amusement
  and meditation, so false alarms there are real false alarms.

Run on the VM (the data lives there)::

    python3 -m ml.models.detector_evaluation --workers 3

Outputs ``ml/reports/detector_wesad.md`` and ``ml/reports/detector_wesad_runs.csv``.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import logging
import math
import sys
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import pandas as pd

from ml.data import loaders
from services.common.schemas import EpisodeEvent
from services.detector.core import DetectorConfig, FixedRuleDetector, PatientDetector

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"

# Physiological arousal outlasts the TSST label by a little; detections in the
# first minute after the label ends still belong to the stress event.
STRESS_GRACE_SECONDS = 60.0

STRESS_LABEL = 2

# Grid explored around the defaults of DetectorConfig. Kept small on purpose: 15
# subjects cannot support fine-grained tuning without overfitting.
HR_Z_THRESHOLDS = (2.0, 2.5, 3.0, 3.5)
ACTIVITY_Z_MAX = (0.5, 1.0)
# EWMA weight per calm window. 0.02 (default) remembers ~8 min, 0.005 ~33 min: a
# longer memory absorbs less of a slow heart-rate rise before the threshold is hit.
BASELINE_ALPHAS = (0.005, 0.02)
# Seconds of recent movement that still explain a high heart rate (recovery).
MOVEMENT_LOOKBACK_SECONDS = (0.0, 180.0, 300.0)
# Minimum EDA z-score; -inf disables the EDA requirement.
EDA_Z_MIN = (-math.inf, 0.0, 1.0)
# The heart-rate std floor (min_std_hr_bpm) was explored in a first run and made no
# difference on WESAD, so it stays at its default.

FIXED_RULE_NAME = "fixed_rule_hr_gt_100"
DEFAULT_NAME = "zscore_default"
V1_NAME = "zscore_v1"
HR_ONLY_PREFIX = "hronly_"
HR_ONLY_DEFAULT_NAME = "hronly_default"
# Heart-rate-only bands (e.g. a Polar H10): EDA is removed from the input and the
# threshold used without EDA is tuned on its own (issue #6).
HR_ONLY_THRESHOLDS = (2.0, 2.5, 3.0, 3.5, 4.0, 4.5)
# Detector v1 as first written in F1-ML-01, kept as a fixed reference point after
# the defaults were updated from this evaluation.
V1_CONFIG = DetectorConfig(
    baseline_alpha=0.02,
    hr_z_threshold=3.0,
    activity_z_max=1.0,
    movement_lookback_seconds=0.0,
    eda_z_min=-math.inf,
)


@dataclass(frozen=True)
class Interval:
    """A time interval in seconds since the start of the recording."""

    start_s: float
    end_s: float


@dataclass
class RunResult:
    """Outcome of one detector configuration on one subject."""

    subject: str
    config_name: str
    stress_events: int
    detected_events: int
    true_episodes: int
    false_alarms: int
    non_stress_hours: float
    first_detection_delay_s: float | None
    false_alarm_conditions: str = ""


def stress_intervals(labels: pd.Series, origin: pd.Timestamp) -> list[Interval]:
    """Return contiguous stress-label intervals, in seconds since ``origin``.

    Args:
        labels: WESAD labels indexed by UTC timestamp (any sampling rate).
        origin: Recording start.

    Returns:
        One interval per contiguous run of label 2.
    """
    is_stress = labels.eq(STRESS_LABEL)
    run_id = is_stress.ne(is_stress.shift()).cumsum()
    intervals = []
    for _, run in labels[is_stress].groupby(run_id[is_stress]):
        intervals.append(
            Interval(
                (run.index[0] - origin).total_seconds(),
                (run.index[-1] - origin).total_seconds(),
            )
        )
    return intervals


def matching_event(time_s: float, stress: Sequence[Interval]) -> int | None:
    """Return the index of the stress event a detection belongs to, or ``None``."""
    for index, event in enumerate(stress):
        if event.start_s <= time_s <= event.end_s + STRESS_GRACE_SECONDS:
            return index
    return None


def false_alarm_conditions(
    detection_times_s: Sequence[float],
    stress: Sequence[Interval],
    conditions: pd.Series,
    origin: pd.Timestamp,
) -> str:
    """Describe where false alarms happened, e.g. ``"amusement:1;baseline:2"``.

    Args:
        detection_times_s: Detection instants in seconds since ``origin``.
        stress: Stress intervals.
        conditions: WESAD condition names indexed by UTC timestamp.
        origin: Recording start.

    Returns:
        Sorted ``condition:count`` pairs for the detections outside stress.
    """
    counts: dict[str, int] = {}
    for time_s in detection_times_s:
        if matching_event(time_s, stress) is not None:
            continue
        # Condition in effect at that instant: last reading at or before it.
        instant = origin + pd.Timedelta(seconds=time_s)
        position = max(conditions.index.searchsorted(instant, side="right") - 1, 0)
        condition = conditions.iloc[position]
        counts[condition] = counts.get(condition, 0) + 1
    return ";".join(f"{name}:{count}" for name, count in sorted(counts.items()))


def score_episodes(
    subject: str,
    config_name: str,
    detection_times_s: Sequence[float],
    stress: Sequence[Interval],
    total_s: float,
) -> RunResult:
    """Match episodes to stress events and count false alarms.

    Args:
        subject: WESAD subject id.
        config_name: Name of the configuration that produced the episodes.
        detection_times_s: Detection instant of each episode (end of its window),
            in seconds since the recording start.
        stress: Stress intervals of the recording.
        total_s: Recording length in seconds.

    Returns:
        Counts for event recall, episode precision and false alarms per hour.
    """
    detected = set()
    true_episodes = 0
    first_delay = None
    for time_s in detection_times_s:
        hit = matching_event(time_s, stress)
        if hit is None:
            continue
        true_episodes += 1
        if hit not in detected and first_delay is None:
            first_delay = time_s - stress[hit].start_s
        detected.add(hit)
    stress_s = sum(event.end_s - event.start_s for event in stress)
    return RunResult(
        subject=subject,
        config_name=config_name,
        stress_events=len(stress),
        detected_events=len(detected),
        true_episodes=true_episodes,
        false_alarms=len(detection_times_s) - true_episodes,
        non_stress_hours=(total_s - stress_s) / 3600,
        first_detection_delay_s=first_delay,
    )


def grid_configs() -> dict[str, DetectorConfig]:
    """Return the named detector configurations explored by the evaluation."""
    configs = {DEFAULT_NAME: DetectorConfig(), V1_NAME: V1_CONFIG}
    for alpha, hr_z, activity_z, lookback, eda_min in itertools.product(
        BASELINE_ALPHAS, HR_Z_THRESHOLDS, ACTIVITY_Z_MAX, MOVEMENT_LOOKBACK_SECONDS, EDA_Z_MIN
    ):
        name = f"zscore_a{alpha}_hr{hr_z}_act{activity_z}_look{lookback:.0f}_eda{eda_min}"
        configs[name] = replace(
            DetectorConfig(),
            baseline_alpha=alpha,
            hr_z_threshold=hr_z,
            activity_z_max=activity_z,
            movement_lookback_seconds=lookback,
            eda_z_min=eda_min,
        )
    return configs


def hr_only_grid_configs() -> dict[str, DetectorConfig]:
    """Return the configurations explored with EDA removed from the input."""
    configs = {HR_ONLY_DEFAULT_NAME: DetectorConfig()}
    for hr_z, activity_z, lookback in itertools.product(
        HR_ONLY_THRESHOLDS, ACTIVITY_Z_MAX, MOVEMENT_LOOKBACK_SECONDS
    ):
        name = f"{HR_ONLY_PREFIX}hr{hr_z}_act{activity_z}_look{lookback:.0f}"
        configs[name] = replace(
            DetectorConfig(),
            hr_z_threshold_without_eda=hr_z,
            activity_z_max=activity_z,
            movement_lookback_seconds=lookback,
        )
    return configs


def _detection_times(episodes: Iterable[EpisodeEvent], window_s: float, origin) -> list[float]:
    """Return each episode's detection instant in seconds since ``origin``."""
    return [(episode.start - origin).total_seconds() + window_s for episode in episodes]


def evaluate_subject(subject: str) -> list[RunResult]:
    """Replay one WESAD subject through every configuration and the fixed rule.

    Args:
        subject: WESAD subject id.

    Returns:
        One result per configuration, plus the fixed rule.
    """
    stream = loaders.load_wesad_wrist(subject)
    origin = stream.index[0]
    total_s = (stream.index[-1] - origin).total_seconds()
    stress = stress_intervals(stream["label"], origin)
    samples = loaders.stream_to_samples(stream)
    without_eda = [sample.model_copy(update={"eda": None}) for sample in samples]
    conditions = stream["condition"]
    del stream
    # Deterministic pseudonym (hash() is salted per process).
    patient_id = "p_" + hashlib.sha256(subject.encode()).hexdigest()[:8]
    results = []
    runs = [(name, config, samples) for name, config in grid_configs().items()]
    runs += [(name, config, without_eda) for name, config in hr_only_grid_configs().items()]
    for name, config, inputs in runs:
        episodes = PatientDetector(patient_id, config).process(inputs)
        times = _detection_times(episodes, config.window_seconds, origin)
        result = score_episodes(subject, name, times, stress, total_s)
        result.false_alarm_conditions = false_alarm_conditions(times, stress, conditions, origin)
        results.append(result)
    fixed = FixedRuleDetector(patient_id).process(samples)
    times = _detection_times(fixed, DetectorConfig().window_seconds, origin)
    result = score_episodes(subject, FIXED_RULE_NAME, times, stress, total_s)
    result.false_alarm_conditions = false_alarm_conditions(times, stress, conditions, origin)
    results.append(result)
    logger.info("Evaluated %s", subject)
    return results


def pooled_metrics(runs: pd.DataFrame) -> dict[str, float]:
    """Pool counts over subjects into event recall, precision, F1 and FA/h.

    Args:
        runs: Rows of :class:`RunResult` for one configuration.

    Returns:
        Metrics dictionary.
    """
    events = runs["stress_events"].sum()
    detected = runs["detected_events"].sum()
    episodes = runs["true_episodes"].sum() + runs["false_alarms"].sum()
    recall = detected / events if events else 0.0
    precision = runs["true_episodes"].sum() / episodes if episodes else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "subjects": float(len(runs)),
        "event_recall": recall,
        "episode_precision": precision,
        "event_f1": f1,
        "false_alarms_per_hour": runs["false_alarms"].sum() / runs["non_stress_hours"].sum(),
        "median_delay_s": runs["first_detection_delay_s"].median(),
    }


def leave_one_subject_out(
    runs: pd.DataFrame, prefix: str = "zscore_"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Choose a configuration per held-out subject using only the other subjects.

    Args:
        runs: All results (every subject x configuration).
        prefix: Only configurations whose name starts with it are candidates
            (``zscore_`` with EDA, ``hronly_`` without).

    Returns:
        ``(held_out_runs, choices)``: the held-out subject's result under the
        configuration chosen without it, and which configuration was chosen.
    """
    candidates = runs[runs["config_name"].str.startswith(prefix)]
    held_out_rows = []
    choices = []
    for subject in sorted(candidates["subject"].unique()):
        training = candidates[candidates["subject"] != subject]
        scores = {
            name: pooled_metrics(group)
            for name, group in training.groupby("config_name", sort=True)
        }
        # Best F1; ties broken by fewer false alarms per hour, then by name.
        best = min(
            scores,
            key=lambda name: (
                -round(scores[name]["event_f1"], 6),
                scores[name]["false_alarms_per_hour"],
                name,
            ),
        )
        choices.append({"held_out": subject, "chosen_config": best})
        held_out_rows.append(
            candidates[(candidates["subject"] == subject) & (candidates["config_name"] == best)]
        )
    return pd.concat(held_out_rows, ignore_index=True), pd.DataFrame(choices)


def build_report(runs: pd.DataFrame) -> str:
    """Render the Markdown report from all runs."""
    held_out, choices = leave_one_subject_out(runs)
    hr_only_held_out, hr_only_choices = leave_one_subject_out(runs, HR_ONLY_PREFIX)

    def _metrics_of(name: str) -> dict[str, float]:
        return pooled_metrics(runs[runs["config_name"] == name])

    summary = pd.DataFrame(
        [
            {"method": "Personal z-score, thresholds chosen by LOSO", **pooled_metrics(held_out)},
            {
                "method": "Personal z-score, deployed defaults (in-sample)",
                **_metrics_of(DEFAULT_NAME),
            },
            {"method": "Personal z-score v1 (initial thresholds)", **_metrics_of(V1_NAME)},
            {
                "method": "HR-only band (EDA removed), thresholds chosen by LOSO",
                **pooled_metrics(hr_only_held_out),
            },
            {
                "method": "HR-only band (EDA removed), deployed defaults (in-sample)",
                **_metrics_of(HR_ONLY_DEFAULT_NAME),
            },
            {"method": "Fixed rule HR > 100 bpm", **_metrics_of(FIXED_RULE_NAME)},
        ]
    )
    most_chosen = pd.concat(
        [choices["chosen_config"], hr_only_choices["chosen_config"]]
    ).value_counts()
    compared = [DEFAULT_NAME, V1_NAME, FIXED_RULE_NAME]
    per_subject = runs[runs["config_name"].isin(compared)].pivot(
        index="subject", columns="config_name", values=["detected_events", "false_alarms"]
    )
    per_subject.columns = [f"{metric}_{name}" for metric, name in per_subject.columns]
    false_alarm_places = (
        runs[runs["config_name"].isin(compared)]
        .assign(condition=lambda frame: frame["false_alarm_conditions"].fillna("").str.split(";"))
        .explode("condition")
        .query("condition != ''")
        .assign(
            count=lambda frame: frame["condition"].str.split(":").str[1].astype(int),
            condition=lambda frame: frame["condition"].str.split(":").str[0],
        )
        .pivot_table(index="condition", columns="config_name", values="count", aggfunc="sum")
        .fillna(0)
        .astype(int)
    )
    defaults = DetectorConfig()
    return "\n".join(
        [
            "# Episode detector on real WESAD wrist data",
            "",
            "Generated by `python3 -m ml.models.detector_evaluation` on LinuxONE. "
            "Stress event = contiguous TSST label; true detection = episode detected "
            f"during stress or up to {STRESS_GRACE_SECONDS:.0f} s after it; every other "
            "episode is a false alarm (baseline, amusement and meditation count as "
            "non-stress). One stress event per subject.",
            "",
            "## Summary",
            "",
            summary.to_markdown(index=False, floatfmt=".2f"),
            "",
            "- **LOSO** is the honest estimate: the thresholds for each subject were chosen "
            "on the other 14 subjects only (best pooled event F1, ties broken by fewer false "
            "alarms per hour).",
            "- **Deployed defaults** is the configuration chosen in most folds, evaluated on "
            "all 15 subjects (in-sample, so optimistic).",
            f"- Deployed defaults: `baseline_alpha={defaults.baseline_alpha}`, "
            f"`hr_z_threshold={defaults.hr_z_threshold}`, "
            f"`activity_z_max={defaults.activity_z_max}`, "
            f"`movement_lookback_seconds={defaults.movement_lookback_seconds:.0f}`, "
            f"`eda_z_min={defaults.eda_z_min}`, "
            f"`hr_z_threshold_without_eda={defaults.hr_z_threshold_without_eda}`.",
            "- **HR-only band** rows replay the same data with EDA removed, as a heart-rate"
            "-only wearable would send it; the EDA check is then skipped and "
            "`hr_z_threshold_without_eda` applies.",
            "",
            "## Configurations chosen across the 15 folds (with EDA and HR-only)",
            "",
            most_chosen.rename_axis("config").reset_index().to_markdown(index=False),
            "",
            "## Where the false alarms happen (WESAD condition at detection time)",
            "",
            "`transient` are the periods between protocol stages, when participants stand "
            "up and walk to the next room: heart rate stays high for a while after sitting "
            "down, which the movement look-back explains.",
            "",
            false_alarm_places.reset_index().to_markdown(index=False),
            "",
            "## Per subject",
            "",
            per_subject.reset_index().to_markdown(index=False),
            "",
            "## Limitations",
            "",
            "- WESAD is a laboratory protocol with 15 young, healthy participants mostly "
            "sitting; it shows whether the personal baseline catches acute stress, not "
            "behaviour in daily life (the nurse dataset covers that, F3-ML-03).",
            "- One stress event per subject: event recall moves in steps of 1/15.",
            "- Heart rate is the Empatica E4's own 1 Hz estimate from BVP.",
            "",
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Evaluate the episode detector on WESAD.")
    parser.add_argument("--subjects", nargs="*", default=loaders.WESAD_SUBJECTS)
    parser.add_argument("--workers", type=int, default=1, help="parallel subjects")
    parser.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the evaluation and write the report and raw runs."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("services.detector.core").setLevel(logging.WARNING)
    args = parse_args(argv)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        nested = list(pool.map(evaluate_subject, args.subjects))
    runs = pd.DataFrame([asdict(result) for results in nested for result in results])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    runs.to_csv(args.out_dir / "detector_wesad_runs.csv", index=False)
    (args.out_dir / "detector_wesad.md").write_text(build_report(runs), encoding="utf-8")
    logger.info("Wrote %s", args.out_dir / "detector_wesad.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
