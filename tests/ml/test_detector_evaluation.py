import pandas as pd

from ml.models import detector_evaluation as ev


def _labels(seconds_and_labels):
    origin = pd.Timestamp("2026-01-01T00:00:00Z")
    index = [origin + pd.Timedelta(seconds=s) for s, _ in seconds_and_labels]
    return pd.Series([label for _, label in seconds_and_labels], index=index), origin


def test_stress_intervals_finds_each_contiguous_stress_run():
    labels, origin = _labels([(0, 1), (10, 2), (20, 2), (30, 1), (40, 2), (50, 3)])
    intervals = ev.stress_intervals(labels, origin)
    assert intervals == [ev.Interval(10, 20), ev.Interval(40, 40)]


def test_score_counts_hits_inside_grace_and_false_alarms_outside():
    stress = [ev.Interval(600, 1200)]
    result = ev.score_episodes(
        "S0", "cfg", [300, 700, 1200 + ev.STRESS_GRACE_SECONDS, 2000], stress, total_s=3600
    )
    assert result.detected_events == 1
    assert result.true_episodes == 2
    assert result.false_alarms == 2
    assert result.first_detection_delay_s == 100
    assert result.non_stress_hours == (3600 - 600) / 3600


def test_score_with_no_episodes_has_zero_recall_and_no_delay():
    result = ev.score_episodes("S0", "cfg", [], [ev.Interval(0, 10)], total_s=100)
    assert result.detected_events == 0 and result.first_detection_delay_s is None


def _run(subject, config, detected, false_alarms):
    return ev.RunResult(
        subject, config, 1, detected, detected, false_alarms, 1.0, 30.0 if detected else None
    )


def test_pooled_metrics_combines_subjects():
    runs = pd.DataFrame([vars(_run("A", "c", 1, 1)), vars(_run("B", "c", 0, 1))])
    metrics = ev.pooled_metrics(runs)
    assert metrics["event_recall"] == 0.5
    assert metrics["episode_precision"] == 1 / 3
    assert metrics["false_alarms_per_hour"] == 1.0


def test_loso_never_uses_the_held_out_subject_to_choose_thresholds():
    # Config "zscore_good" wins on A and B; on C only "zscore_bad" detects. When C is
    # held out, the choice must come from A and B ("zscore_good"), even though it
    # performs worse on C.
    rows = [
        _run("A", "zscore_good", 1, 0), _run("A", "zscore_bad", 0, 3),
        _run("B", "zscore_good", 1, 0), _run("B", "zscore_bad", 0, 3),
        _run("C", "zscore_good", 0, 0), _run("C", "zscore_bad", 1, 0),
    ]  # fmt: skip
    held_out, choices = ev.leave_one_subject_out(pd.DataFrame([vars(r) for r in rows]))
    chosen = dict(zip(choices["held_out"], choices["chosen_config"], strict=True))
    assert chosen["C"] == "zscore_good"
    assert held_out.set_index("subject").loc["C", "detected_events"] == 0


def test_grid_contains_default_and_varies_thresholds():
    configs = ev.grid_configs()
    assert ev.DEFAULT_NAME in configs
    assert {c.hr_z_threshold for c in configs.values()} >= set(ev.HR_Z_THRESHOLDS)


def test_false_alarm_conditions_names_where_each_false_alarm_happened():
    # 150 s is a true detection (stress ends at 100 s, grace 60 s); 50 and 310 s fall
    # in baseline, 250 s in amusement.
    labels, origin = _labels([(0, 1), (100, 2), (200, 3), (300, 1)])
    conditions = labels.map({1: "baseline", 2: "stress", 3: "amusement"})
    stress = ev.stress_intervals(labels, origin)
    text = ev.false_alarm_conditions([50, 150, 250, 310], stress, conditions, origin)
    assert text == "amusement:1;baseline:2"


def test_hr_only_grid_varies_the_threshold_used_without_eda():
    configs = ev.hr_only_grid_configs()
    assert ev.HR_ONLY_DEFAULT_NAME in configs
    assert all(name.startswith(ev.HR_ONLY_PREFIX) for name in configs)
    assert {c.hr_z_threshold_without_eda for c in configs.values()} >= set(ev.HR_ONLY_THRESHOLDS)


def test_loso_prefix_keeps_eda_and_hr_only_candidates_apart():
    rows = [_run("A", "zscore_x", 1, 0), _run("A", "hronly_y", 0, 0),
            _run("B", "zscore_x", 1, 0), _run("B", "hronly_y", 0, 0)]  # fmt: skip
    _, choices = ev.leave_one_subject_out(pd.DataFrame([vars(r) for r in rows]), "hronly_")
    assert set(choices["chosen_config"]) == {"hronly_y"}
