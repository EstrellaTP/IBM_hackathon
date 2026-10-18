"""Turn a recorded wrist stream into a schedule of SignalBatches to send.

Pure functions (no network), used by :mod:`tools.simulator.simulate` and tested on
synthetic data.

Timing model:

* The recording is cut into batches of ``batch_seconds`` of signal, as a phone that
  uploads every few seconds would send them.
* Every sample time is shifted by one constant so that the moment where real-time
  replay starts (``realtime_from_s`` into the recording) maps to "now". Samples before
  it end up in the past and are sent as fast as possible (fast-forward, so the
  detector builds its personal baseline without waiting); later batches are sent when
  the wall clock reaches the end of the batch, i.e. at real speed. Because samples
  keep their real spacing, the detector sees exactly the recorded signal.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from ml.data import loaders
from services.common.schemas import Sample


@dataclass(frozen=True)
class ScheduledBatch:
    """Samples of one batch and the wall-clock time at which to send them."""

    send_at: datetime
    samples: list[Sample]
    realtime: bool


def stress_start_seconds(stream: pd.DataFrame) -> float | None:
    """Seconds from the start of the recording to the first stress label, if any."""
    stress = stream.index[stream["condition"] == "stress"]
    if len(stress) == 0:
        return None
    return (stress[0] - stream.index[0]).total_seconds()


def schedule_batches(
    stream: pd.DataFrame,
    now: datetime,
    batch_seconds: float = 10.0,
    realtime_from_s: float = 0.0,
    until_s: float | None = None,
) -> Iterator[ScheduledBatch]:
    """Yield the batches of a recording with re-based timestamps and send times.

    Args:
        stream: Wrist stream indexed by UTC time (``loaders.load_wesad_wrist`` layout).
        now: Wall-clock time at which the real-time part starts.
        batch_seconds: Signal seconds per batch.
        realtime_from_s: Seconds into the recording where real-time replay starts;
            earlier batches are sent immediately.
        until_s: Stop after this many seconds of recording (``None``: until the end).

    Yields:
        Batches in time order.
    """
    origin = stream.index[0]
    shift = now - (origin + timedelta(seconds=realtime_from_s))
    if until_s is not None:
        stream = stream[stream.index < origin + timedelta(seconds=until_s)]
    shifted = stream.copy()
    shifted.index = shifted.index + shift
    samples = loaders.stream_to_samples(shifted)
    if not samples:
        return
    batch: list[Sample] = []
    batch_end = samples[0].t + timedelta(seconds=batch_seconds)
    for sample in samples:
        if sample.t >= batch_end:
            yield _scheduled(batch, batch_end, now)
            batch = []
            while sample.t >= batch_end:
                batch_end += timedelta(seconds=batch_seconds)
        batch.append(sample)
    if batch:
        yield _scheduled(batch, batch_end, now)


def _scheduled(samples: list[Sample], batch_end: datetime, now: datetime) -> ScheduledBatch:
    """A batch is sent when its last second of signal has 'happened'."""
    realtime = batch_end > now
    return ScheduledBatch(
        send_at=batch_end if realtime else now, samples=samples, realtime=realtime
    )
