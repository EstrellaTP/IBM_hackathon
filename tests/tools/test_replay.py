from datetime import datetime, timedelta, timezone

import pytest

from ml.data import synthetic
from tools.simulator.replay import schedule_batches, stress_start_seconds
from tools.simulator.simulate import parse_args

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def test_stress_start_is_found_in_the_labels():
    stream = synthetic.wesad_wrist_stream(duration_s=2000, seed=1)
    assert stress_start_seconds(stream) == 1200


def test_batches_before_realtime_are_sent_now_and_later_ones_at_real_speed():
    stream = synthetic.wesad_wrist_stream(duration_s=120, periods=(), seed=1)
    batches = list(schedule_batches(stream, NOW, batch_seconds=10, realtime_from_s=60))
    fast = [b for b in batches if not b.realtime]
    live = [b for b in batches if b.realtime]
    assert len(fast) == 6 and len(live) == 6
    assert all(b.send_at == NOW for b in fast)
    # Real-time batches leave every 10 s of wall clock, at the end of their signal.
    assert [b.send_at - NOW for b in live] == [timedelta(seconds=10 * i) for i in range(1, 7)]


def test_rebased_samples_keep_their_spacing_and_reach_now_at_realtime_start():
    stream = synthetic.wesad_wrist_stream(duration_s=60, periods=(), seed=1)
    batches = list(schedule_batches(stream, NOW, batch_seconds=10, realtime_from_s=30))
    samples = [s for b in batches for s in b.samples]
    assert len(samples) == len(stream)
    assert samples[0].t == NOW - timedelta(seconds=30)
    # Every reading sits on the 32 Hz accelerometer grid; spacing is preserved.
    gaps = {
        round((b.t - a.t).total_seconds() * 32, 6)
        for a, b in zip(samples, samples[1:], strict=False)
    }
    assert gaps == {1.0}


def test_until_limits_the_replay():
    stream = synthetic.wesad_wrist_stream(duration_s=600, periods=(), seed=1)
    batches = list(schedule_batches(stream, NOW, batch_seconds=60, until_s=120))
    assert len(batches) == 2


def test_simulator_rejects_a_patient_id_that_is_not_a_pseudonym():
    with pytest.raises(SystemExit):
        parse_args(["--synthetic", "--patient-id", "p_dem0010"])
    assert parse_args(["--synthetic", "--patient-id", "p_dec0010"]).patient_id == "p_dec0010"


def test_all_fast_forward_ends_now_instead_of_shifting_into_the_past():
    stream = synthetic.wesad_wrist_stream(duration_s=120, periods=(), seed=1)
    batches = list(schedule_batches(stream, NOW, batch_seconds=10, realtime_from_s=1e9))
    assert not any(b.realtime for b in batches)
    last = batches[-1].samples[-1].t
    assert NOW - timedelta(seconds=20) <= last <= NOW
