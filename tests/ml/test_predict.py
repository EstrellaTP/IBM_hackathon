import math

import numpy as np
from sklearn.model_selection import GroupKFold

from ml.models import train
from ml.models.predict import load_model
from tests.ml.test_train import _feature_table


def _exported(tmp_path, model_name, people):
    table = _feature_table(people, 0.3, 7, "p")
    x, y, groups = train.prepare(table)
    train.export_portable_model(
        model_name, x, y, groups, tmp_path, GroupKFold(train.N_SPLITS), "synthetic"
    )
    return load_model(tmp_path), x


def test_logistic_contributions_add_up_to_the_raw_score(tmp_path):
    model, x = _exported(tmp_path, "logistic", 120)
    row = x.iloc[0].to_dict()
    prediction = model.predict(row)
    total = sum(prediction.contributions.values()) + model.meta["logistic"]["intercept"]
    assert math.isclose(total, prediction.raw_score, rel_tol=1e-9)
    assert 0 <= prediction.probability <= 1
    assert prediction.compatible == (prediction.probability >= model.threshold)


def test_missing_features_are_imputed_with_training_medians(tmp_path):
    model, x = _exported(tmp_path, "logistic", 120)
    row = x.iloc[0].to_dict()
    row["iv"] = float("nan")
    del row["ra"]
    assert np.isfinite(model.predict(row).probability)


def test_lightgbm_model_loads_from_text_and_explains_with_tree_contributions(tmp_path):
    model, x = _exported(tmp_path, "lightgbm", 600)
    prediction = model.predict(x.iloc[3].to_dict())
    assert set(prediction.contributions) == set(train.FEATURES)
    assert model.meta["calibration"]["type"] == "isotonic"
    assert model.version == "lightgbm-synthetic-600"


def test_raw_features_are_scaled_like_the_training_population():
    from ml.features import circadian

    table = _feature_table(80, 0.3, 9, "p")
    stats = circadian.device_scaling_stats(table, circadian.DEVICE_SCALED_FEATURES)
    scaled = circadian.standardise_within_dataset(
        table[train.FEATURES], circadian.DEVICE_SCALED_FEATURES
    )
    raw_row = table.iloc[5][train.FEATURES].to_dict()
    applied = circadian.apply_device_scaling(raw_row, stats)
    for column in circadian.DEVICE_SCALED_FEATURES:
        assert math.isclose(applied[column], scaled.iloc[5][column], rel_tol=1e-9, abs_tol=1e-12)


def test_sigmoid_is_stable_for_extreme_scores():
    from ml.models.predict import sigmoid

    assert sigmoid(1000.0) == 1.0 and sigmoid(-1000.0) == 0.0
    assert math.isclose(sigmoid(0.0), 0.5)
