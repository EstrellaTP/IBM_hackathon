from ml.data import loaders, synthetic
from ml.data.synthetic import Period
from ml.models.iforest_detector import IsolationForestConfig, IsolationForestDetector


def _episode_starts(stream, detector):
    episodes = detector.process(loaders.stream_to_samples(stream))
    return [(e.start - stream.index[0]).total_seconds() for e in episodes], episodes


def test_isolation_forest_flags_synthetic_stress():
    stream = synthetic.wesad_wrist_stream(
        duration_s=2400, periods=(Period(1500, 2100, "stress"),), seed=3
    )
    starts, episodes = _episode_starts(stream, IsolationForestDetector("p_0f0f0f0f"))
    assert any(1500 - 60 <= s < 2100 for s in starts)
    assert all(e.method.value == "iforest" for e in episodes)


def test_isolation_forest_ignores_exercise_with_the_movement_rule():
    stream = synthetic.wesad_wrist_stream(
        duration_s=2400, periods=(Period(1500, 1800, "exercise"),), seed=4
    )
    starts, _ = _episode_starts(stream, IsolationForestDetector("p_0f0f0f0f"))
    assert not any(1500 - 60 <= s < 1800 + 180 for s in starts)


def test_no_episode_during_calibration():
    stream = synthetic.wesad_wrist_stream(
        duration_s=500, periods=(Period(100, 400, "stress"),), seed=5
    )
    detector = IsolationForestDetector("p_0f0f0f0f", IsolationForestConfig(calibration_windows=60))
    assert detector.process(loaders.stream_to_samples(stream)) == []
