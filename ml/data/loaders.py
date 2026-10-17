"""Reproducible loaders for the raw datasets in ``ml/data/raw/`` (task F0-ML-02).

Every loader returns a :class:`pandas.DataFrame` with English ``snake_case`` columns
and documented units, so features, models and the simulator never touch the raw
formats. Column lists are module constants shared with :mod:`ml.data.synthetic`,
which generates data with exactly the same layout for tests.

Byte order (the VM is big-endian s390x, CLAUDE.md §6):

* CSV files (DEPRESJON, Empatica E4) are text: no byte-order issue.
* SAS XPORT (NHANES) is big-endian IBM floating point by specification; pandas
  converts it explicitly, independent of the host. A known quirk of that
  conversion turns 0 into ``5.397605e-79``, fixed by :func:`clean_xport_frame`.
* WESAD pickles store the dtype (with its byte order) next to the raw bytes; numpy
  restores the values correctly on either architecture. Arrays are then cast to the
  native ``float64`` so downstream code never mixes byte orders.

The WESAD pickle is opened with a restricted unpickler that only rebuilds numpy
arrays: a pickle can otherwise execute arbitrary code.
"""

from __future__ import annotations

import io
import logging
import os
import pickle
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from services.common.schemas import Sample

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "raw"


def data_dir() -> Path:
    """Return the raw data directory (``$HOLTER_DATA_DIR`` or ``ml/data/raw``)."""
    return Path(os.environ.get("HOLTER_DATA_DIR", DEFAULT_DATA_DIR))


# ---------------------------------------------------------------------------
# NHANES (SAS XPORT)
# ---------------------------------------------------------------------------

# pandas decodes an IBM-float zero as 5.397605e-79 (smallest IBM exponent with a
# zero mantissa). Anything below this magnitude in NHANES is a true zero.
XPORT_ZERO_TOLERANCE = 1e-70

# NHANES file suffix and folder per survey cycle.
NHANES_CYCLES = {"G": 2011, "H": 2013}

# The PAM device sampled at 80 Hz; PAXSSN* columns are sample indices from the start.
NHANES_PAM_SAMPLING_HZ = 80

# PHQ-9 items DPQ010..DPQ090; DPQ100 (functional difficulty) is not part of the score.
PHQ9_ITEMS = [f"DPQ0{i}0" for i in range(1, 10)]
PHQ9_VALID_ANSWERS = {0, 1, 2, 3}  # 7 = refused, 9 = don't know -> incomplete
# PHQ-9 >= 10 is the usual cut-off for moderate depressive symptoms (Kroenke et al.,
# J Gen Intern Med 2001). It measures symptoms, it does not diagnose (CLAUDE.md §7).
PHQ9_SYMPTOMS_CUTOFF = 10

DEMOGRAPHICS_COLUMNS = ["seqn", "sex", "age_years", "exam_weight"]
PHQ9_COLUMNS = ["seqn", "phq9_total", "depressive_symptoms"]
PAX_HEADER_COLUMNS = ["seqn", "pax_status", "first_day_of_week", "first_time_s", "wrist"]
PAX_HOURLY_COLUMNS = [
    "seqn",
    "day",
    "day_of_week",
    "clock_hour_start_s",
    "minutes_measured",
    "mims",
    "wake_wear_min",
    "sleep_wear_min",
    "nonwear_min",
    "unknown_min",
    "quality_flag",
]

_PAX_HOURLY_RENAME = {
    "SEQN": "seqn",
    "PAXDAYH": "day",
    "PAXDAYWH": "day_of_week",
    "PAXTMH": "minutes_measured",
    "PAXMTSH": "mims",
    "PAXWWMH": "wake_wear_min",
    "PAXSWMH": "sleep_wear_min",
    "PAXNWMH": "nonwear_min",
    "PAXUMH": "unknown_min",
    "PAXQFH": "quality_flag",
}


def clean_xport_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Fix the two pandas XPORT quirks: fake zeros and ``bytes`` text columns.

    Args:
        frame: Frame as returned by ``pandas.read_sas(..., format="xport")``.

    Returns:
        A copy where tiny magnitudes are exactly 0 and text columns are ``str``.
    """
    cleaned = frame.copy()
    for column in cleaned.columns:
        series = cleaned[column]
        if pd.api.types.is_float_dtype(series):
            cleaned[column] = series.mask(series.abs() < XPORT_ZERO_TOLERANCE, 0.0)
        elif series.dtype == object:
            cleaned[column] = series.map(
                lambda value: value.decode("ascii").strip() if isinstance(value, bytes) else value
            )
    return cleaned


def _nhanes_path(name: str, cycle: str, root: Path | None) -> Path:
    """Return the path of an NHANES table such as ``DEMO`` for a cycle."""
    year = NHANES_CYCLES[cycle]
    return (root or data_dir()) / "nhanes" / str(year) / f"{name}_{cycle}.xpt"


def read_xpt(path: Path) -> pd.DataFrame:
    """Read a whole XPORT file and clean it (see :func:`clean_xport_frame`)."""
    return clean_xport_frame(pd.read_sas(path, format="xport"))


def demographics_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Map a raw ``DEMO`` table to :data:`DEMOGRAPHICS_COLUMNS`.

    ``RIAGENDR`` 1 = male, 2 = female. ``RIDAGEYR`` is top-coded at 80 by NHANES.
    """
    frame = pd.DataFrame(
        {
            "seqn": raw["SEQN"].astype("int64"),
            "sex": raw["RIAGENDR"].map({1.0: "M", 2.0: "F"}),
            "age_years": raw["RIDAGEYR"].astype("float64"),
            "exam_weight": raw["WTMEC2YR"].astype("float64"),
        }
    )
    return frame[DEMOGRAPHICS_COLUMNS]


def phq9_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Score PHQ-9 from a raw ``DPQ`` table, keeping complete questionnaires only.

    A questionnaire is complete when all nine items are answered 0-3; refused (7),
    don't know (9) or missing answers exclude the person (CLAUDE.md §7).

    Args:
        raw: Cleaned ``DPQ`` table.

    Returns:
        Frame with :data:`PHQ9_COLUMNS`; ``depressive_symptoms`` is PHQ-9 >= 10.
    """
    items = raw[PHQ9_ITEMS]
    complete = items.isin(PHQ9_VALID_ANSWERS).all(axis=1)
    total = items[complete].sum(axis=1).astype("int64")
    frame = pd.DataFrame(
        {
            "seqn": raw.loc[complete, "SEQN"].astype("int64"),
            "phq9_total": total,
            "depressive_symptoms": total >= PHQ9_SYMPTOMS_CUTOFF,
        }
    )
    return frame.reset_index(drop=True)[PHQ9_COLUMNS]


def _clock_seconds(text: pd.Series) -> pd.Series:
    """Convert ``"H:MM:SS"`` strings to seconds after midnight (``NaN`` if empty)."""
    return pd.to_timedelta(text.str.strip(), errors="coerce").dt.total_seconds()


def pax_header_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Map a raw ``PAXHD`` table to :data:`PAX_HEADER_COLUMNS`.

    ``PAXSTS`` 1 = data available; ``PAXFDAY`` day of week of the first day
    (1 = Sunday); ``PAXFTIME`` start time. ``wrist`` keeps the raw ``PAXHAND`` code
    (see the PAXHD_H documentation for its meaning).
    """
    frame = pd.DataFrame(
        {
            "seqn": raw["SEQN"].astype("int64"),
            "pax_status": raw["PAXSTS"].astype("float64"),
            # Participants without accelerometer data have empty day/time fields.
            "first_day_of_week": pd.to_numeric(raw["PAXFDAY"], errors="coerce").astype("Int64"),
            "first_time_s": _clock_seconds(raw["PAXFTIME"]),
            "wrist": pd.to_numeric(raw["PAXHAND"], errors="coerce"),
        }
    )
    return frame[PAX_HEADER_COLUMNS]


def pax_hourly_from_raw(raw: pd.DataFrame, header: pd.DataFrame) -> pd.DataFrame:
    """Map a raw ``PAXHR`` table to :data:`PAX_HOURLY_COLUMNS`.

    The clock time of each hourly row is the recording start time (``PAXFTIME``)
    plus ``PAXSSNHP`` samples at 80 Hz, wrapped to a day. The first and last rows of
    a recording can cover less than 60 minutes (``minutes_measured``).

    Args:
        raw: Cleaned ``PAXHR`` rows (whole file or one chunk).
        header: Output of :func:`pax_header_from_raw`.

    Returns:
        Frame with :data:`PAX_HOURLY_COLUMNS`; MIMS is the triaxial sum per hour.
    """
    frame = raw.rename(columns=_PAX_HOURLY_RENAME)
    frame["seqn"] = frame["seqn"].astype("int64")
    frame["day"] = pd.to_numeric(frame["day"]).astype("int64")
    frame["day_of_week"] = pd.to_numeric(frame["day_of_week"]).astype("int64")
    start = frame["seqn"].map(header.set_index("seqn")["first_time_s"])
    offset_s = frame["PAXSSNHP"] / NHANES_PAM_SAMPLING_HZ
    frame["clock_hour_start_s"] = ((start + offset_s) % 86_400).round().astype("int64")
    return frame[PAX_HOURLY_COLUMNS].reset_index(drop=True)


def load_nhanes_demographics(cycle: str = "H", root: Path | None = None) -> pd.DataFrame:
    """Load sex, age and exam weight for one NHANES cycle."""
    return demographics_from_raw(read_xpt(_nhanes_path("DEMO", cycle, root)))


def load_nhanes_phq9(cycle: str = "H", root: Path | None = None) -> pd.DataFrame:
    """Load complete PHQ-9 questionnaires with total score and symptom label."""
    return phq9_from_raw(read_xpt(_nhanes_path("DPQ", cycle, root)))


def load_nhanes_pax_header(cycle: str = "H", root: Path | None = None) -> pd.DataFrame:
    """Load the accelerometer recording header (start day and time, wrist)."""
    return pax_header_from_raw(read_xpt(_nhanes_path("PAXHD", cycle, root)))


def load_nhanes_pax_hourly(
    cycle: str = "H", root: Path | None = None, chunksize: int = 200_000
) -> pd.DataFrame:
    """Load hourly MIMS and wear/sleep minutes for every participant.

    The file is read in chunks to keep memory low on the VM.

    Args:
        cycle: NHANES cycle letter (only ``"H"`` has hourly files in this project).
        root: Data directory override.
        chunksize: Rows per chunk.

    Returns:
        Frame with :data:`PAX_HOURLY_COLUMNS`.
    """
    header = load_nhanes_pax_header(cycle, root)
    reader = pd.read_sas(_nhanes_path("PAXHR", cycle, root), format="xport", chunksize=chunksize)
    chunks = [pax_hourly_from_raw(clean_xport_frame(chunk), header) for chunk in reader]
    return pd.concat(chunks, ignore_index=True)


# ---------------------------------------------------------------------------
# DEPRESJON (CSV, Garcia-Ceja et al. 2018)
# ---------------------------------------------------------------------------

DEPRESJON_SCORES_COLUMNS = [
    "person_id",
    "group",
    "sex",
    "age_group",
    "affective_type",
    "madrs_start",
    "madrs_end",
    "days",
]
DEPRESJON_ACTIVITY_COLUMNS = ["timestamp", "activity"]

# scores.csv codes (dataset README): gender 1 = female, 2 = male; afftype
# 1 = bipolar II, 2 = unipolar depressive, 3 = bipolar I. Controls have no afftype.
_DEPRESJON_SEX = {1: "F", 2: "M"}
_DEPRESJON_AFFECTIVE_TYPE = {1: "bipolar_ii", 2: "unipolar", 3: "bipolar_i"}


def depresjon_scores_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Map DEPRESJON ``scores.csv`` to :data:`DEPRESJON_SCORES_COLUMNS`."""
    frame = pd.DataFrame(
        {
            "person_id": raw["number"],
            "group": raw["number"].str.split("_").str[0],
            "sex": pd.to_numeric(raw["gender"]).map(_DEPRESJON_SEX),
            "age_group": raw["age"],
            "affective_type": pd.to_numeric(raw["afftype"], errors="coerce").map(
                _DEPRESJON_AFFECTIVE_TYPE
            ),
            "madrs_start": pd.to_numeric(raw["madrs1"], errors="coerce"),
            "madrs_end": pd.to_numeric(raw["madrs2"], errors="coerce"),
            "days": pd.to_numeric(raw["days"]).astype("int64"),
        }
    )
    return frame[DEPRESJON_SCORES_COLUMNS]


def load_depresjon_scores(root: Path | None = None) -> pd.DataFrame:
    """Load one row per DEPRESJON participant (23 patients, 32 controls)."""
    path = (root or data_dir()) / "depresjon" / "data" / "scores.csv"
    return depresjon_scores_from_raw(pd.read_csv(path, dtype=str))


def load_depresjon_activity(person_id: str, root: Path | None = None) -> pd.DataFrame:
    """Load the minute-level activity counts of one DEPRESJON participant.

    Timestamps are naive local (Norwegian) clock time as recorded by the Actiwatch;
    the dataset gives no time zone. Circadian features only need clock time.

    Args:
        person_id: ``condition_<n>`` or ``control_<n>``.
        root: Data directory override.

    Returns:
        Frame with :data:`DEPRESJON_ACTIVITY_COLUMNS` (``activity`` in device counts).
    """
    group = person_id.split("_")[0]
    path = (root or data_dir()) / "depresjon" / "data" / group / f"{person_id}.csv"
    raw = pd.read_csv(path, parse_dates=["timestamp"])
    frame = raw[DEPRESJON_ACTIVITY_COLUMNS].copy()
    frame["activity"] = frame["activity"].astype("int64")
    return frame


# ---------------------------------------------------------------------------
# WESAD wrist (Empatica E4), Schmidt et al. 2018
# ---------------------------------------------------------------------------

# S1 and S12 were discarded by the dataset authors (sensor malfunction).
WESAD_SUBJECTS = [f"S{n}" for n in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17)]
WESAD_LABEL_HZ = 700  # RespiBAN rate; labels are sampled at this rate.
E4_ACC_HZ = 32
E4_ACC_UNITS_PER_G = 64  # E4 accelerometer range +-2 g, 1/64 g per unit.
WESAD_CONDITIONS = {
    0: "transient",
    1: "baseline",
    2: "stress",
    3: "amusement",
    4: "meditation",
    5: "ignore",
    6: "ignore",
    7: "ignore",
}
WESAD_WRIST_COLUMNS = ["hr", "acc_x", "acc_y", "acc_z", "eda", "label", "condition"]

# Samples of the pickle's wrist ACC used to locate it inside ACC.csv. 64 samples
# (2 s) of three axes are unique in practice; the full match is then verified.
_ALIGNMENT_PROBE_SAMPLES = 64

_ALLOWED_PICKLE_GLOBALS = {
    ("numpy.core.multiarray", "_reconstruct"),
    ("numpy._core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"),
    ("numpy._core.multiarray", "scalar"),
    ("numpy", "ndarray"),
    ("numpy", "dtype"),
    ("_codecs", "encode"),
}


class _NumpyOnlyUnpickler(pickle.Unpickler):
    """Unpickler that refuses every global except those needed for numpy arrays."""

    def find_class(self, module: str, name: str) -> object:
        if (module, name) not in _ALLOWED_PICKLE_GLOBALS:
            raise pickle.UnpicklingError(f"blocked global {module}.{name} in pickle")
        return super().find_class(module, name)


def load_wesad_pickle(path: Path) -> dict:
    """Load a WESAD ``S*.pkl`` safely (numpy arrays only, Python 2 latin-1 strings)."""
    with path.open("rb") as handle:
        return _NumpyOnlyUnpickler(handle, encoding="latin1").load()


def read_e4_csv(archive: zipfile.ZipFile, name: str) -> tuple[float, float, np.ndarray]:
    """Read one Empatica E4 CSV from its zip export.

    Row 1 is the start time (Unix seconds, UTC), row 2 the sampling rate in Hz,
    then one row per sample (one column per axis for ACC).

    Returns:
        ``(start_unix_s, rate_hz, values)`` with ``values`` as native float64, 2-D.
    """
    lines = archive.read(name).decode("ascii").splitlines()
    start = float(lines[0].split(",")[0])
    rate = float(lines[1].split(",")[0])
    values = np.loadtxt(io.StringIO("\n".join(lines[2:])), delimiter=",", ndmin=2)
    return start, rate, values.astype(np.float64)


def find_alignment_offset(full: np.ndarray, segment: np.ndarray) -> int:
    """Return the index where ``segment`` appears inside ``full`` (exact match).

    Args:
        full: Complete E4 recording, shape ``(n, axes)``.
        segment: Synchronised excerpt stored in the WESAD pickle.

    Returns:
        Start index of ``segment`` within ``full``.

    Raises:
        ValueError: If the segment is not found or only its beginning matches.
    """
    probe = segment[:_ALIGNMENT_PROBE_SAMPLES]
    width = len(probe)
    matches = np.flatnonzero((full[: len(full) - width + 1] == probe[0]).all(axis=1))
    for index in matches:
        if np.array_equal(full[index : index + width], probe):
            if not np.array_equal(full[index : index + len(segment)], segment):
                raise ValueError("pickle segment matches ACC.csv only at its start")
            return int(index)
    raise ValueError("pickle wrist ACC not found inside ACC.csv")


def load_wesad_wrist(
    subject: str, root: Path | None = None, acc_hz: int = E4_ACC_HZ
) -> pd.DataFrame:
    """Load the synchronised wrist signals of one WESAD subject as a sample stream.

    The result mirrors what the band would send: one row per sensor reading at the
    sensor's own rate (ACC 32 Hz, HR 1 Hz, EDA 4 Hz), with ``NaN`` in the columns of
    sensors that did not sample at that instant. This keeps per-sample activity
    (ENMO) intact for the detector. HR comes from the E4's own 1 Hz ``HR.csv``
    (derived from BVP on the device); the pickle has no HR.

    The pickle holds the protocol window synchronised with the labels; it is found
    inside the full E4 export by exact matching of the accelerometer samples, which
    gives absolute UTC timestamps for every sensor.

    Args:
        subject: One of :data:`WESAD_SUBJECTS`.
        root: Data directory override.
        acc_hz: Accelerometer output rate; values below 32 average consecutive
            samples (useful for large benchmarks, but it under-estimates ENMO).

    Returns:
        Frame indexed by UTC timestamp ``t`` with :data:`WESAD_WRIST_COLUMNS`;
        accelerometer in g, HR in bpm, EDA in µS, ``label`` the WESAD protocol code.
    """
    if E4_ACC_HZ % acc_hz:
        raise ValueError(f"acc_hz must divide {E4_ACC_HZ}")
    folder = (root or data_dir()) / "wesad" / "WESAD" / subject
    record = load_wesad_pickle(folder / f"{subject}.pkl")
    wrist_acc = np.asarray(record["signal"]["wrist"]["ACC"], dtype=np.float64)
    labels = np.asarray(record["label"], dtype=np.int64)

    with zipfile.ZipFile(folder / f"{subject}_E4_Data.zip") as archive:
        acc_start, acc_rate, acc_full = read_e4_csv(archive, "ACC.csv")
        hr_start, hr_rate, hr_values = read_e4_csv(archive, "HR.csv")
        eda_start, eda_rate, eda_values = read_e4_csv(archive, "EDA.csv")

    offset = find_alignment_offset(acc_full, wrist_acc)
    window_start = acc_start + offset / acc_rate
    window_end = window_start + len(labels) / WESAD_LABEL_HZ

    acc = wrist_acc / E4_ACC_UNITS_PER_G
    factor = E4_ACC_HZ // acc_hz
    usable = len(acc) - len(acc) % factor
    acc = acc[:usable].reshape(-1, factor, 3).mean(axis=1)
    acc_times = window_start + np.arange(len(acc)) * factor / acc_rate

    hr_times = hr_start + np.arange(len(hr_values)) / hr_rate
    eda_times = eda_start + np.arange(len(eda_values)) / eda_rate

    def _in_window(times: np.ndarray) -> np.ndarray:
        return (times >= window_start) & (times < window_end)

    frames = [
        pd.DataFrame({"t": acc_times, "acc_x": acc[:, 0], "acc_y": acc[:, 1], "acc_z": acc[:, 2]}),
        pd.DataFrame({"t": hr_times, "hr": hr_values[:, 0]})[_in_window(hr_times)],
        pd.DataFrame({"t": eda_times, "eda": eda_values[:, 0]})[_in_window(eda_times)],
    ]
    stream = pd.concat(frames, ignore_index=True)
    stream = stream.groupby("t", sort=True).first()  # merge readings at the same instant
    label_index = np.minimum(
        ((stream.index.to_numpy() - window_start) * WESAD_LABEL_HZ).astype(np.int64),
        len(labels) - 1,
    )
    stream["label"] = labels[label_index]
    stream["condition"] = stream["label"].map(WESAD_CONDITIONS)
    stream.index = pd.to_datetime(stream.index, unit="s", utc=True)
    stream.index.name = "t"
    logger.info("WESAD %s: %d rows, %.0f s window", subject, len(stream), window_end - window_start)
    return stream[WESAD_WRIST_COLUMNS]


def stream_to_samples(stream: pd.DataFrame) -> list[Sample]:
    """Convert a wrist stream (WESAD or synthetic) into contract ``Sample`` objects.

    ``NaN`` becomes ``None`` so each sample only carries the sensors that measured at
    that instant, as a real band would send them.

    Args:
        stream: Frame indexed by UTC ``t`` with ``hr``, ``acc_*`` and ``eda`` columns.

    Returns:
        Samples sorted by time, ready for a ``SignalBatch`` or the detector.
    """
    columns = ["hr", "acc_x", "acc_y", "acc_z", "eda"]
    values = stream[columns].astype("float64").to_numpy()
    samples = []
    for timestamp, row in zip(stream.index.to_pydatetime(), values, strict=True):
        fields = {name: float(v) for name, v in zip(columns, row, strict=True) if not np.isnan(v)}
        samples.append(Sample(t=timestamp, **fields))
    return samples
