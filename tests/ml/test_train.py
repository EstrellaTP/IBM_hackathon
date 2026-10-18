import json

import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import GroupKFold

from ml.models import train


def _feature_table(people: int, prevalence: float, seed: int, prefix: str) -> pd.DataFrame:
    """Synthetic per-person features where positives have lower amplitude and activity."""
    rng = np.random.default_rng(seed)
    label = (rng.random(people) < prevalence).astype(int)
    frame = pd.DataFrame({name: rng.normal(0, 1, people) for name in train.FEATURES})
    frame["ra"] = 0.8 - 0.15 * label + rng.normal(0, 0.05, people)
    frame["daytime_activity"] = np.exp(5 - 0.5 * label + rng.normal(0, 0.3, people))
    frame["l5"] = np.exp(rng.normal(2, 0.5, people))
    frame["m10"] = np.exp(rng.normal(6, 0.5, people))
    frame["label"] = label
    frame["person_id"] = [f"{prefix}_{i}" for i in range(people)]
    frame["sex"] = rng.choice(["F", "M"], people)
    frame["age_years"] = rng.integers(18, 80, people)
    frame["valid_days"] = 7
    return frame


def test_disjoint_group_check_catches_person_leakage():
    groups = np.array(["a", "b", "c", "a"])
    with pytest.raises(AssertionError, match="leakage"):
        train.assert_disjoint_groups(groups, np.array([0, 1]), np.array([2, 3]))
    train.assert_disjoint_groups(groups, np.array([0, 3]), np.array([1, 2]))


def test_group_kfold_never_puts_a_person_in_train_and_test():
    table = _feature_table(200, 0.2, 0, "p")
    # Duplicate rows of the same people (as if there were several days per person).
    table = pd.concat([table, table], ignore_index=True)
    x, y, groups = train.prepare(table)
    for tr, te in GroupKFold(train.N_SPLITS).split(x, y, groups):
        train.assert_disjoint_groups(groups, tr, te)


def test_metrics_are_computed_per_person_with_fixed_threshold():
    y = np.array([1, 1, 0, 0])
    p = np.array([0.9, 0.2, 0.3, 0.1])
    m = train.compute_metrics(y, p, np.full(4, 0.25))
    assert (m.sensitivity, m.specificity) == (0.5, 0.5)
    assert m.auc == pytest.approx(0.75)


def test_out_of_fold_learns_the_planted_signal_and_is_calibrated():
    table = _feature_table(1500, 0.15, 1, "p")
    x, y, groups = train.prepare(table)
    probability, threshold = train.out_of_fold(
        train.make_models()["logistic"], x, y, groups, GroupKFold(train.N_SPLITS)
    )
    metrics = train.compute_metrics(y, probability, threshold)
    assert metrics.auc > 0.85
    reliability = train.reliability_table(y, probability)
    assert train.expected_calibration_error(reliability) < 0.08


def test_full_run_writes_report_figures_and_portable_model(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    _feature_table(600, 0.12, 2, "nhanes").to_csv(processed / "features_nhanes.csv", index=False)
    depresjon = _feature_table(40, 0.4, 3, "dep")
    depresjon.to_csv(processed / "features_depresjon.csv", index=False)
    report = train.run(processed, tmp_path / "reports", tmp_path / "artifacts")
    assert "GroupKFold" in report and "leave-one-subject-out" in report
    assert (tmp_path / "reports" / "reliability.svg").read_text().startswith("<svg")
    assert (tmp_path / "reports" / "fairness.svg").exists()
    meta = json.loads((tmp_path / "artifacts" / "depression_model.json").read_text())
    assert meta["features"] == train.FEATURES
    assert 0 < meta["threshold"] < 1
    assert meta["calibration"]["x"] and len(meta["calibration"]["x"]) == len(
        meta["calibration"]["y"]
    )


def test_plan_b_deploys_a_depresjon_model_with_platt_calibration(tmp_path, monkeypatch):
    monkeypatch.setattr(train, "TRANSFER_AUC_MIN", 1.01)  # force "does not transfer"
    processed = tmp_path / "processed"
    processed.mkdir()
    _feature_table(600, 0.12, 4, "nhanes").to_csv(processed / "features_nhanes.csv", index=False)
    _feature_table(40, 0.4, 5, "dep").to_csv(processed / "features_depresjon.csv", index=False)
    report = train.run(processed, tmp_path / "reports", tmp_path / "artifacts")
    meta = json.loads((tmp_path / "artifacts" / "depression_model.json").read_text())
    assert meta["trained_on"] == "depresjon"
    assert meta["calibration"]["type"] == "platt"
    assert meta["model"] in train.DEPLOYABLE_MODELS
    assert "Plan B applies" in report
