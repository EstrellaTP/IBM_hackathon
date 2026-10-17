import io
import os
import pickle
import zipfile

import numpy as np
import pandas as pd
import pytest

from ml.data import loaders, synthetic
from services.detector.core import PatientDetector

XPORT_FAKE_ZERO = 5.397605346934028e-79


# --- NHANES -----------------------------------------------------------------


def test_clean_xport_frame_turns_fake_zeros_into_zero_and_decodes_bytes():
    raw = pd.DataFrame({"x": [XPORT_FAKE_ZERO, 2.0], "s": [b" 7:30:00", b"abc"]})
    cleaned = loaders.clean_xport_frame(raw)
    assert cleaned["x"].tolist() == [0.0, 2.0]
    assert cleaned["s"].tolist() == ["7:30:00", "abc"]


def _dpq(rows):
    columns = ["SEQN", *loaders.PHQ9_ITEMS]
    return pd.DataFrame(rows, columns=columns)


def test_phq9_scores_complete_questionnaires_and_flags_cutoff():
    raw = _dpq([[1, *[1] * 9], [2, *[2] * 5, 0, 0, 0, 0], [3, *[0] * 9]])
    scored = loaders.phq9_from_raw(raw)
    assert scored["phq9_total"].tolist() == [9, 10, 0]
    assert scored["depressive_symptoms"].tolist() == [False, True, False]
    assert list(scored.columns) == loaders.PHQ9_COLUMNS


@pytest.mark.parametrize("bad_answer", [7, 9, np.nan])
def test_phq9_excludes_refused_unknown_or_missing_answers(bad_answer):
    raw = _dpq([[1, bad_answer, *[1] * 8], [2, *[1] * 9]])
    assert loaders.phq9_from_raw(raw)["seqn"].tolist() == [2]


def test_demographics_maps_sex_codes():
    raw = pd.DataFrame(
        {"SEQN": [1.0, 2.0], "RIAGENDR": [1.0, 2.0], "RIDAGEYR": [30.0, 80.0], "WTMEC2YR": [1, 2]}
    )
    frame = loaders.demographics_from_raw(raw)
    assert frame["sex"].tolist() == ["M", "F"]
    assert list(frame.columns) == loaders.DEMOGRAPHICS_COLUMNS


def test_pax_header_tolerates_participants_without_accelerometer_data():
    raw = pd.DataFrame(
        {
            "SEQN": [1.0, 2.0],
            "PAXSTS": [1.0, 2.0],
            "PAXFDAY": ["3", ""],
            "PAXFTIME": ["16:30:00", ""],
            "PAXHAND": ["1", ""],
        }
    )
    header = loaders.pax_header_from_raw(raw)
    assert header.loc[0, "first_time_s"] == 16.5 * 3600
    assert pd.isna(header.loc[1, "first_time_s"])
    assert pd.isna(header.loc[1, "first_day_of_week"])


def test_pax_hourly_clock_time_comes_from_start_time_plus_samples_and_wraps_midnight():
    header = pd.DataFrame({"seqn": [1], "first_time_s": [23.5 * 3600]})
    raw = pd.DataFrame(
        {
            "SEQN": [1.0, 1.0],
            "PAXDAYH": ["1", "2"],
            "PAXDAYWH": ["3", "4"],
            "PAXSSNHP": [0.0, 1800 * loaders.NHANES_PAM_SAMPLING_HZ],
            "PAXTMH": [30.0, 60.0],
            "PAXMTSH": [600.0, 50.0],
            "PAXWWMH": [30.0, 0.0],
            "PAXSWMH": [0.0, 60.0],
            "PAXNWMH": [0.0, 0.0],
            "PAXUMH": [0.0, 0.0],
            "PAXQFH": [0.0, 0.0],
        }
    )
    hourly = loaders.pax_hourly_from_raw(raw, header)
    assert hourly["clock_hour_start_s"].tolist() == [23.5 * 3600, 0]
    assert list(hourly.columns) == loaders.PAX_HOURLY_COLUMNS


# --- DEPRESJON --------------------------------------------------------------


def test_depresjon_scores_and_activity_load_from_dataset_layout(tmp_path):
    folder = tmp_path / "depresjon" / "data"
    (folder / "condition").mkdir(parents=True)
    (folder / "scores.csv").write_text(
        "number,days,gender,age,afftype,melanch,inpatient,edu,marriage,work,madrs1,madrs2\n"
        "condition_1,2,1,35-39,2,2,2,6-10,1,2,19,15\n"
        "control_1,2,2,20-24,,,,,,,,\n",
        encoding="utf-8",
    )
    (folder / "condition" / "condition_1.csv").write_text(
        "timestamp,date,activity\n2003-05-07 12:00:00,2003-05-07,0\n"
        "2003-05-07 12:01:00,2003-05-07,143\n",
        encoding="utf-8",
    )
    scores = loaders.load_depresjon_scores(tmp_path)
    assert scores["group"].tolist() == ["condition", "control"]
    assert scores["sex"].tolist() == ["F", "M"]
    assert scores.loc[0, "affective_type"] == "unipolar"
    assert pd.isna(scores.loc[1, "madrs_start"])
    activity = loaders.load_depresjon_activity("condition_1", tmp_path)
    assert activity["activity"].tolist() == [0, 143]
    assert list(activity.columns) == loaders.DEPRESJON_ACTIVITY_COLUMNS


# --- WESAD ------------------------------------------------------------------

E4_START = 1_500_000_000.0
PRE_ROLL_SAMPLES = 320  # 10 s of E4 recording before the synchronised window
WINDOW_SECONDS = 20


def _e4_csv(start, rate, rows):
    header = f"{start:.6f}\n{rate:.6f}\n"
    return header + "\n".join(",".join(f"{v:g}" for v in np.atleast_1d(r)) for r in rows)


def _make_wesad_subject(root):
    rng = np.random.default_rng(1)
    acc_units = rng.integers(-60, 60, size=(PRE_ROLL_SAMPLES + WINDOW_SECONDS * 32, 3))
    acc_units[:, 2] = 64  # 1 g on z
    acc_units[:, 0] = np.arange(len(acc_units)) % 50  # make every sample distinct
    window = acc_units[PRE_ROLL_SAMPLES:].astype(np.float64)
    labels = np.repeat([1, 2], WINDOW_SECONDS * 700 // 2).astype(np.int32)
    folder = root / "wesad" / "WESAD" / "S2"
    folder.mkdir(parents=True)
    record = {"signal": {"wrist": {"ACC": window}}, "label": labels, "subject": "S2"}
    (folder / "S2.pkl").write_bytes(pickle.dumps(record))
    seconds = (PRE_ROLL_SAMPLES / 32) + WINDOW_SECONDS
    with zipfile.ZipFile(folder / "S2_E4_Data.zip", "w") as archive:
        archive.writestr("ACC.csv", _e4_csv(E4_START, 32, acc_units))
        archive.writestr("HR.csv", _e4_csv(E4_START, 1, [[80.0]] * int(seconds)))
        archive.writestr("EDA.csv", _e4_csv(E4_START, 4, [[0.5]] * int(seconds * 4)))


def test_wesad_wrist_is_aligned_converted_to_g_and_labelled(tmp_path):
    _make_wesad_subject(tmp_path)
    stream = loaders.load_wesad_wrist("S2", tmp_path)
    window_start = pd.Timestamp(E4_START + PRE_ROLL_SAMPLES / 32, unit="s", tz="UTC")
    assert stream.index[0] == window_start
    assert str(stream.index.tz) == "UTC"
    assert stream["acc_z"].dropna().eq(1.0).all()  # 64 units -> 1 g
    assert stream["hr"].count() == WINDOW_SECONDS
    assert stream["eda"].count() == WINDOW_SECONDS * 4
    first_half = stream.index < window_start + pd.Timedelta(seconds=WINDOW_SECONDS / 2)
    assert set(stream.loc[first_half, "condition"]) == {"baseline"}
    assert set(stream.loc[~first_half, "condition"]) == {"stress"}
    assert list(stream.columns) == loaders.WESAD_WRIST_COLUMNS


def test_wesad_wrist_can_average_accelerometer_to_a_lower_rate(tmp_path):
    _make_wesad_subject(tmp_path)
    stream = loaders.load_wesad_wrist("S2", tmp_path, acc_hz=4)
    assert stream["acc_x"].count() == WINDOW_SECONDS * 4


class _Exploit:
    def __reduce__(self):
        return (os.system, ("echo pwned",))


def test_wesad_pickle_loader_refuses_non_numpy_globals(tmp_path):
    path = tmp_path / "evil.pkl"
    path.write_bytes(pickle.dumps({"signal": _Exploit()}))
    with pytest.raises(pickle.UnpicklingError, match="blocked global"):
        loaders.load_wesad_pickle(path)


def test_alignment_fails_loudly_when_segment_is_absent():
    full = np.arange(300, dtype=np.float64).reshape(-1, 3)
    with pytest.raises(ValueError, match="not found"):
        loaders.find_alignment_offset(full, full[:70] + 0.5)


def test_e4_csv_reader_returns_start_rate_and_native_float_values():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("HR.csv", _e4_csv(E4_START, 1, [[70.5], [71.0]]))
    with zipfile.ZipFile(buffer) as archive:
        start, rate, values = loaders.read_e4_csv(archive, "HR.csv")
    assert (start, rate) == (E4_START, 1.0)
    assert values.dtype.isnative and values[:, 0].tolist() == [70.5, 71.0]


# --- Synthetic data matches the loaders and drives the detector ---------------


def test_synthetic_frames_have_the_loader_layouts():
    stream = synthetic.wesad_wrist_stream(duration_s=60, periods=())
    assert list(stream.columns) == loaders.WESAD_WRIST_COLUMNS
    assert str(stream.index.tz) == "UTC"
    activity = synthetic.depresjon_activity(days=1)
    assert list(activity.columns) == loaders.DEPRESJON_ACTIVITY_COLUMNS
    demographics, phq9, hourly = synthetic.nhanes_tables(people=5, days=1)
    assert list(demographics.columns) == loaders.DEMOGRAPHICS_COLUMNS
    assert list(phq9.columns) == loaders.PHQ9_COLUMNS
    assert list(hourly.columns) == loaders.PAX_HOURLY_COLUMNS


def test_stream_to_samples_keeps_only_measured_sensors():
    stream = synthetic.wesad_wrist_stream(duration_s=2, periods=())
    samples = loaders.stream_to_samples(stream)
    assert len(samples) == len(stream)
    first = samples[0]  # t = 0 s: ACC, HR and EDA all sampled
    assert first.hr is not None and first.eda is not None and first.acc_z is not None
    assert samples[1].hr is None  # t = 1/32 s: ACC only


def test_detector_flags_synthetic_stress_but_not_synthetic_exercise():
    stream = synthetic.wesad_wrist_stream(duration_s=3000, seed=3)
    episodes = PatientDetector("p_abc123").process(loaders.stream_to_samples(stream))
    # ``start`` is the beginning of the 60 s window that triggered the episode
    # (``detected_at`` is wall-clock time, not signal time).
    window_s = 60
    starts = [(e.start - stream.index[0]).total_seconds() for e in episodes]
    assert any(1200 - window_s <= s < 1800 for s in starts)
    assert not any(2400 - window_s <= s < 2700 for s in starts)
