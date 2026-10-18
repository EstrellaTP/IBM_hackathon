import numpy as np
import pandas as pd
import pytest

from ml.features import daily
from ml.models import reference_ranges as rr
from tests.ml.test_circadian import _series, _square_wave


def test_daily_metrics_of_a_regular_day():
    days = daily.daily_metrics(_series(3, _square_wave))
    assert list(days.columns) == daily.DAILY_COLUMNS
    assert days["sleep"].tolist() == [10.0, 10.0, 10.0]  # 22:00-08:00 at rest
    assert days["circadian_rhythm"].tolist() == [1.0, 1.0, 1.0]
    assert days["daytime_activity"].tolist() == [1.0, 1.0, 1.0]


def test_daily_metrics_are_scale_free():
    small = daily.daily_metrics(_series(3, _square_wave))
    large = daily.daily_metrics(_series(3, lambda d, h: 1000 * _square_wave(d, h)))
    pd.testing.assert_frame_equal(small, large)


def test_weighted_percentile_matches_unweighted_with_equal_weights():
    values = np.arange(1, 101, dtype=float)
    assert rr.weighted_percentile(values, np.ones(100), 50) == pytest.approx(50.5)


def test_weighted_percentile_follows_the_weights():
    values = np.array([1.0, 10.0])
    assert rr.weighted_percentile(values, np.array([9.0, 1.0]), 50) < 5


def test_reference_ranges_are_grouped_by_sex_and_age():
    people = pd.DataFrame(
        {
            "sex": ["F", "F", "M"],
            "age_years": [35.0, 36.0, 72.0],
            "exam_weight": [1.0, 1.0, 1.0],
            "sleep": [7.0, 9.0, 8.0],
            "circadian_rhythm": [0.8, 0.9, 0.7],
            "daytime_activity": [0.6, 0.7, 0.5],
        }
    )
    result = rr.reference_ranges(people)
    band = result["ranges"]["sleep"]["F_30-39"]
    assert band["p10"] <= band["p50"] <= band["p90"] and band["people"] == 2
    assert "M_70+" in result["ranges"]["circadian_rhythm"]
    assert result["heart_rate"] is None


def test_daytime_activity_is_continuous_and_lower_on_a_slower_day():
    def slower_day_2(day, hour):
        return _square_wave(day, hour) * (0.5 if day == 2 else 1.0)

    days = daily.daily_metrics(_series(3, slower_day_2))
    values = days.set_index("day")["daytime_activity"]
    assert values[2] < values[1] and 0 < values[2] < 1
