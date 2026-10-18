r"""Replay wrist signal to ingest-api as one or many patients' bands would (F1-BE-04).

Runs on the LinuxONE VM, where the datasets live::

    # WESAD subject S10: fast-forward until 2 min before the stress test, then real time
    python3 -m tools.simulator.simulate --wesad S10 --lead-seconds 120 \\
        --url https://localhost:8443 --insecure --patient-id p_demo0001

    # synthetic signal, 10 patients, everything as fast as possible
    python3 -m tools.simulator.simulate --synthetic --patients 10 --realtime-from 1e9

Each episode returned by ingest-api is printed with its stage timestamps, so the
terminal shows the detection happening on LinuxONE (useful for the demo video).
Replayed data is labelled as such on the phone ("replayed WESAD data").
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass, field

import httpx
import pandas as pd

from ml.data import loaders, synthetic
from services.common.schemas import (
    PATIENT_ID_PATTERN,
    Device,
    SignalBatch,
    new_patient_id,
    utcnow,
)
from tools.device import device_headers
from tools.simulator.replay import schedule_batches, stress_start_seconds

logger = logging.getLogger("simulator")

INGEST_PATH = "/api/v1/signal-batches"


@dataclass
class PatientStats:
    """What one simulated patient sent and received."""

    patient_id: str
    batches: int = 0
    samples: int = 0
    episodes: list[dict] = field(default_factory=list)
    errors: int = 0


def load_stream(args: argparse.Namespace, seed: int) -> tuple[pd.DataFrame, Device]:
    """Load the recording to replay (WESAD subject or synthetic)."""
    if args.wesad:
        return loaders.load_wesad_wrist(args.wesad, acc_hz=args.acc_hz), Device.WESAD
    stream = synthetic.wesad_wrist_stream(duration_s=args.synthetic_seconds, seed=seed)
    return stream, Device.SIM


def realtime_start(stream: pd.DataFrame, args: argparse.Namespace) -> float:
    """Seconds into the recording where real-time replay starts."""
    if args.realtime_from is not None:
        return args.realtime_from
    stress = stress_start_seconds(stream)
    return max(0.0, (stress or 0.0) - args.lead_seconds)


async def run_patient(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    patient_id: str,
    stream: pd.DataFrame,
    device: Device,
) -> PatientStats:
    """Send one patient's batches on schedule and collect the episodes returned."""
    stats = PatientStats(patient_id)
    start_s = realtime_start(stream, args)
    for scheduled in schedule_batches(
        stream, utcnow(), args.batch_seconds, start_s, args.until_seconds
    ):
        delay = (scheduled.send_at - utcnow()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        batch = SignalBatch(
            patient_id=patient_id, device=device, sent_at=utcnow(), samples=scheduled.samples
        )
        try:
            response = await client.post(
                INGEST_PATH,
                content=batch.model_dump_json(),
                headers=device_headers(),
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            stats.errors += 1
            logger.warning("patient=%s batch failed: %s", patient_id, error)
            continue
        stats.batches += 1
        stats.samples += len(batch.samples)
        for episode in response.json()["episodes"]:
            stats.episodes.append(episode)
            _print_episode(episode, scheduled.realtime)
    return stats


def _print_episode(episode: dict, realtime: bool) -> None:
    stamps = episode["timestamps"]
    logger.info(
        "EPISODE %s patient=%s severity=%s hr_z=%s | signal %s | ingested %s | inferred %s "
        "| pushed %s%s",
        episode["episode_id"],
        episode["patient_id"],
        episode["severity"],
        episode["features"].get("hr_z"),
        stamps["sample_t"][11:19],
        (stamps.get("ingested_at") or "")[11:23],
        (stamps.get("inferred_at") or "")[11:23],
        (stamps.get("pushed_at") or "")[11:23] or "no phone connected",
        "" if realtime else " (fast-forward)",
    )


async def main_async(args: argparse.Namespace) -> int:
    """Run every simulated patient concurrently and print a summary."""
    patient_ids = [args.patient_id] if args.patient_id else []
    patient_ids += [new_patient_id() for _ in range(args.patients - len(patient_ids))]
    async with httpx.AsyncClient(
        base_url=args.url, verify=not args.insecure, timeout=args.timeout
    ) as client:
        tasks = []
        for index, patient_id in enumerate(patient_ids):
            stream, device = load_stream(args, seed=index)
            logger.info(
                "patient=%s replaying %s, real time from %.0f s",
                patient_id,
                args.wesad or "synthetic signal",
                realtime_start(stream, args),
            )
            tasks.append(run_patient(client, args, patient_id, stream, device))
        results = await asyncio.gather(*tasks)
    for stats in results:
        logger.info(
            "SUMMARY patient=%s batches=%d samples=%d episodes=%d errors=%d",
            stats.patient_id,
            stats.batches,
            stats.samples,
            len(stats.episodes),
            stats.errors,
        )
    return 1 if any(stats.errors for stats in results) else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Replay wrist signal to ingest-api.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wesad", choices=loaders.WESAD_SUBJECTS, help="WESAD subject to replay")
    source.add_argument("--synthetic", action="store_true", help="replay synthetic signal")
    parser.add_argument("--synthetic-seconds", type=int, default=3000)
    parser.add_argument("--url", default="https://localhost:8443", help="gateway base URL")
    parser.add_argument("--insecure", action="store_true", help="accept the self-signed cert")
    parser.add_argument("--patient-id", help="pseudonymous id of the first patient")
    parser.add_argument("--patients", type=int, default=1, help="patients replayed at once")
    parser.add_argument("--batch-seconds", type=float, default=10.0, help="signal per batch")
    parser.add_argument(
        "--lead-seconds", type=float, default=120.0, help="real time starts this long before stress"
    )
    parser.add_argument(
        "--realtime-from", type=float, help="seconds into the recording where real time starts"
    )
    parser.add_argument("--until-seconds", type=float, help="stop after this much recording")
    parser.add_argument(
        "--acc-hz", type=int, default=loaders.E4_ACC_HZ, help="accelerometer rate sent"
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.patient_id and not re.fullmatch(PATIENT_ID_PATTERN, args.patient_id):
        parser.error(f"--patient-id must match {PATIENT_ID_PATTERN} (p_ + hex), e.g. p_dec0010")
    args.patients = max(args.patients, 1)
    return args


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
