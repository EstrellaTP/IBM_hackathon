import math

import numpy as np
import pandas as pd
import pytest

from ml.features import circadian as cf


def _series(days, activity_of_hour, valid=lambda day, hour: True):
    rows = [
        {"day": d, "hour": h, "activity": activity_of_hour(d, h), "valid": valid(d, h)}
        for d in range(1, days + 1)
        for h in range(24)
    ]
    return pd.DataFrame(rows)


def _square_wave(day, hour):
    return 100.0 if cf.DAY_START_HOUR <= hour < cf.DAY_END_HOUR else 0.0


def test_identical_days_have_maximal_interdaily_stability():
    hourly = _series(7, _square_wave)
    assert cf.interdaily_stability(hourly) == pytest.approx(1.0)


def test_white_noise_has_intradaily_variability_near_two():
    rng = np.random.default_rng(0)
    noise = rng.normal(100, 10, 24 * 60)
    hourly = _series(60, lambda d, h: noise[(d - 1) * 24 + h])
    assert cf.intradaily_variability(hourly) == pytest.approx(2.0, abs=0.15)


def test_smooth_rhythm_has_low_intradaily_variability():
    hourly = _series(7, lambda d, h: 100 + 50 * math.sin(2 * math.pi * h / 24))
    assert cf.intradaily_variability(hourly) < 0.1


def test_square_wave_gives_textbook_l5_m10_and_relative_amplitude():
    features = cf.person_features(_series(7, _square_wave))
    assert features["l5"] == 0.0
    assert features["m10"] == 100.0
    assert features["ra"] == 1.0
    assert cf.DAY_START_HOUR <= features["m10_start_h"] <= cf.DAY_END_HOUR - cf.M10_HOURS
    assert features["rest_hours_per_day"] == 24 - (cf.DAY_END_HOUR - cf.DAY_START_HOUR)
    assert features["sedentary_share"] == 0.0
    assert features["night_fragmentation"] == 0.0
    assert features["daily_total_cv"] == 0.0
    assert features["valid_days"] == 7


def test_one_awakening_per_night_is_counted_once_even_across_midnight():
    def wakes_at_3am(day, hour):
        return 100.0 if hour == 3 else _square_wave(day, hour)

    features = cf.person_features(_series(7, wakes_at_3am))
    # The first night is truncated by the recording start, so allow 6/7..1.
    assert 0.8 <= features["night_fragmentation"] <= 1.0


def test_days_with_too_few_valid_hours_are_ignored():
    def invalid_day_3(day, hour):
        return not (day == 3 and hour < 10)

    hourly = _series(5, _square_wave, valid=invalid_day_3)
    assert cf.person_features(hourly)["valid_days"] == 4


def test_no_valid_days_returns_nan_features():
    hourly = _series(2, _square_wave, valid=lambda d, h: False)
    features = cf.person_features(hourly)
    assert features["valid_days"] == 0 and math.isnan(features["is_"])


def test_flatter_lower_rhythm_has_lower_relative_amplitude():
    healthy = cf.person_features(_series(7, _square_wave))
    flat = cf.person_features(_series(7, lambda d, h: 20.0 + 0.4 * _square_wave(d, h)))
    assert flat["ra"] < healthy["ra"]


def test_standardisation_makes_device_scaled_columns_unitless():
    frame = pd.DataFrame({"l5": [1.0, 10.0, 100.0], "ra": [0.5, 0.6, 0.7]})
    scaled = cf.standardise_within_dataset(frame, ["l5"])
    assert scaled["l5"].mean() == pytest.approx(0.0)
    assert scaled["l5"].std(ddof=0) == pytest.approx(1.0)
    assert scaled["ra"].tolist() == [0.5, 0.6, 0.7]
