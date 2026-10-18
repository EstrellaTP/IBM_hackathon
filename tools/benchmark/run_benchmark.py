r"""Latency benchmark: 1, 10, 100 and 1,000 patients sending signal at once (F3-BE-01/02).

Every simulated patient sends one ``SignalBatch`` every ``--interval`` seconds (10 s of
synthetic wrist signal, accelerometer at 4 Hz to keep the client light), for
``--duration`` seconds per load level. For each request it records:

* ``detector_ms``: pure detection compute inside the detector (the IBM Z part);
* ``server_ms``: ``ingested_at -> responded_at`` inside ingest-api (detector call,
  storage and audit, all on LinuxONE);
* ``client_ms``: round trip seen by the client (adds TLS and the network).

Server times come from the response, so the network never contaminates them; this is
how the pitch separates "LinuxONE latency" from "the hop to the US".

::

    python -m tools.benchmark.run_benchmark --url https://148.100.99.58:8443 --insecure \\
        --levels 1 10 100 1000 --duration 120 --out ml/reports

Outputs ``benchmark.csv`` (one row per request), ``benchmark.md`` (p50/p99 per level)
and ``benchmark.svg`` (p50/p99 against the number of patients).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import random
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from ml.data import synthetic
from services.common.schemas import new_patient_id, utcnow
from tools.device import device_headers

logger = logging.getLogger("benchmark")

INGEST_PATH = "/api/v1/signal-batches"
BATCH_SECONDS = 10
ACC_HZ_FOR_BENCHMARK = 4  # lighter than the E4's 32 Hz; same rows for HR and EDA


@dataclass
class RequestResult:
    """Timings of one request."""

    patients: int
    patient_id: str
    sent_at: float
    status: int
    client_ms: float
    server_ms: float | None
    detector_ms: float | None
    episodes: int


def batch_template() -> list[dict]:
    """10 s of calm synthetic signal as JSON-ready samples with relative times (s)."""
    stream = synthetic.wesad_wrist_stream(duration_s=BATCH_SECONDS, periods=(), seed=1)
    step = len(stream[stream["acc_x"].notna()]) // (BATCH_SECONDS * ACC_HZ_FOR_BENCHMARK)
    acc_rows = stream[stream["acc_x"].notna()].iloc[::step]
    keep = stream["hr"].notna() | stream["eda"].notna() | stream.index.isin(acc_rows.index)
    stream = stream[keep]
    origin = stream.index[0]
    samples = []
    for timestamp, row in stream.iterrows():
        sample = {"offset": (timestamp - origin).total_seconds()}
        for column in ("hr", "acc_x", "acc_y", "acc_z", "eda"):
            if not np.isnan(row[column]):
                sample[column] = round(float(row[column]), 4)
        samples.append(sample)
    return samples


def build_body(patient_id: str, template: list[dict], start: datetime) -> bytes:
    """Serialise one batch whose samples start at ``start``."""
    samples = []
    for item in template:
        sample = {k: v for k, v in item.items() if k != "offset"}
        sample["t"] = (start + timedelta(seconds=item["offset"])).isoformat()
        samples.append(sample)
    body = {
        "patient_id": patient_id,
        "device": "sim",
        "sent_at": utcnow().isoformat(),
        "samples": samples,
    }
    return json.dumps(body).encode()


async def patient_loop(
    client: httpx.AsyncClient,
    patient_id: str,
    patients: int,
    template: list[dict],
    deadline: float,
    interval: float,
    results: list[RequestResult],
) -> None:
    """Send one batch per interval until the deadline, recording timings."""
    await asyncio.sleep(random.uniform(0, interval))  # spread patients over the interval
    signal_start = utcnow() - timedelta(seconds=BATCH_SECONDS)
    while time.monotonic() < deadline:
        body = build_body(patient_id, template, signal_start)
        signal_start += timedelta(seconds=BATCH_SECONDS)
        sent = time.monotonic()
        try:
            response = await client.post(INGEST_PATH, content=body, headers=device_headers())
            client_ms = (time.monotonic() - sent) * 1000
            server_ms = detector_ms = None
            episodes = 0
            if response.status_code == httpx.codes.ACCEPTED:
                payload = response.json()
                timings = payload.get("timings", {})
                if timings.get("ingested_at") and timings.get("responded_at"):
                    server_ms = (
                        datetime.fromisoformat(timings["responded_at"])
                        - datetime.fromisoformat(timings["ingested_at"])
                    ).total_seconds() * 1000
                detector_ms = timings.get("detector_inference_ms")
                episodes = len(payload["episodes"])
            results.append(
                RequestResult(
                    patients,
                    patient_id,
                    sent,
                    response.status_code,
                    client_ms,
                    server_ms,
                    detector_ms,
                    episodes,
                )
            )
        except httpx.HTTPError as error:
            results.append(
                RequestResult(
                    patients, patient_id, sent, 0, (time.monotonic() - sent) * 1000, None, None, 0
                )
            )
            logger.debug("request failed: %s", error)
        await asyncio.sleep(max(0.0, interval - (time.monotonic() - sent)))


async def run_level(
    url: str, insecure: bool, patients: int, duration: float, interval: float, template: list[dict]
) -> list[RequestResult]:
    """Run one load level and return its request results."""
    results: list[RequestResult] = []
    limits = httpx.Limits(
        max_connections=min(patients, 200), max_keepalive_connections=min(patients, 200)
    )
    async with httpx.AsyncClient(
        base_url=url, verify=not insecure, timeout=60, limits=limits
    ) as client:
        deadline = time.monotonic() + duration
        await asyncio.gather(
            *(
                patient_loop(
                    client, new_patient_id(), patients, template, deadline, interval, results
                )
                for _ in range(patients)
            )
        )
    return results


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    """p50/p99 of each timing and throughput per load level."""
    rows = []
    for patients, group in results.groupby("patients"):
        ok = group[group["status"] == httpx.codes.ACCEPTED]
        row = {
            "patients": patients,
            "requests": len(group),
            "errors": int((group["status"] != httpx.codes.ACCEPTED).sum()),
        }
        span = group["sent_at"].max() - group["sent_at"].min()
        row["requests_per_s"] = len(group) / span if span > 0 else float("nan")
        for column in ("detector_ms", "server_ms", "client_ms"):
            values = ok[column].dropna()
            row[f"{column}_p50"] = values.quantile(0.5) if len(values) else float("nan")
            row[f"{column}_p99"] = values.quantile(0.99) if len(values) else float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def svg_chart(summary: pd.DataFrame, path: Path) -> None:
    """p50/p99 of server and detector time against patients (log x), dependency-free SVG."""
    width, height, pad = 520, 320, 50
    levels = summary["patients"].tolist()
    series = {
        "server p99": ("server_ms_p99", "#dc2626", "6"),
        "server p50": ("server_ms_p50", "#dc2626", "0"),
        "detector p99": ("detector_ms_p99", "#2563eb", "6"),
        "detector p50": ("detector_ms_p50", "#2563eb", "0"),
    }
    top = max(float(summary[[c for c, _, _ in series.values()]].max().max()), 1.0) * 1.15
    log_min, log_max = (
        np.log10(min(levels)),
        np.log10(max(levels)) if max(levels) > min(levels) else np.log10(min(levels)) + 1,
    )

    def xy(patients: float, ms: float) -> tuple[float, float]:
        fraction = (
            (np.log10(patients) - log_min) / (log_max - log_min) if log_max > log_min else 0.5
        )
        return pad + fraction * (width - 2 * pad - 90), height - pad - ms / top * (height - 2 * pad)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'font-family="sans-serif" font-size="11">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{pad}" y="20">Server-side latency on LinuxONE vs concurrent patients</text>',
        f'<text x="{width / 2 - 60}" y="{height - 10}">patients (log scale)</text>',
        f'<text x="6" y="{pad - 10}">ms</text>',
    ]
    for level in levels:
        x, y = xy(level, 0)
        parts.append(f'<text x="{x - 8}" y="{y + 16}">{level}</text>')
    for tick in np.linspace(0, top, 5):
        x, y = xy(levels[0], tick)
        parts.append(f'<text x="{pad - 40}" y="{y + 4}">{tick:.0f}</text>')
        parts.append(f'<line x1="{pad}" y1="{y}" x2="{width - pad - 90}" y2="{y}" stroke="#eee"/>')
    for index, (label, (column, colour, dash)) in enumerate(series.items()):
        points = " ".join(
            "{:.1f},{:.1f}".format(*xy(p, v))
            for p, v in zip(levels, summary[column], strict=True)
            if not np.isnan(v)
        )
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{colour}" '
            f'stroke-width="2" stroke-dasharray="{dash}"/>'
        )
        parts.append(
            f'<text x="{width - pad - 80}" y="{pad + 16 * index}" fill="{colour}">{label}</text>'
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run every level, write CSV, Markdown summary and SVG chart."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Latency benchmark against ingest-api.")
    parser.add_argument("--url", default="https://localhost:8443")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--levels", type=int, nargs="+", default=[1, 10, 100, 1000])
    parser.add_argument("--duration", type=float, default=120.0, help="seconds per level")
    parser.add_argument(
        "--interval", type=float, default=BATCH_SECONDS, help="seconds between batches per patient"
    )
    parser.add_argument("--out", type=Path, default=Path("ml/reports"))
    parser.add_argument("--client-location", default="laptop (Madrid) over the internet")
    args = parser.parse_args(argv)
    template = batch_template()
    all_results: list[RequestResult] = []
    for patients in args.levels:
        logger.info("level %d patients, %.0f s", patients, args.duration)
        results = asyncio.run(
            run_level(args.url, args.insecure, patients, args.duration, args.interval, template)
        )
        all_results += results
        level = summarise(pd.DataFrame([asdict(r) for r in results]))
        logger.info("%s", level.round(1).to_dict("records"))
    frame = pd.DataFrame([asdict(r) for r in all_results])
    args.out.mkdir(parents=True, exist_ok=True)
    frame.drop(columns=["patient_id"]).to_csv(
        args.out / "benchmark.csv", index=False, quoting=csv.QUOTE_MINIMAL
    )
    summary = summarise(frame)
    svg_chart(summary, args.out / "benchmark.svg")
    (args.out / "benchmark.md").write_text(
        "\n".join(
            [
                "# Latency benchmark on LinuxONE",
                "",
                "Generated by `python -m tools.benchmark.run_benchmark`. "
                f"Client: {args.client_location}. Each patient sends {BATCH_SECONDS} s of "
                f"synthetic wrist signal every {args.interval:.0f} s (accelerometer at "
                f"{ACC_HZ_FOR_BENCHMARK} Hz, HR 1 Hz, EDA 4 Hz) ",
                f"for {args.duration:.0f} s per level.",
                "",
                "- `detector_ms`: detection compute inside the detector container (IBM Z).",
                "- `server_ms`: ingest-api from `ingested_at` to the response (detector call, "
                "encrypted storage, audit), all on LinuxONE.",
                "- `client_ms`: round trip seen by the client (adds TLS and the network).",
                "",
                summary.to_markdown(index=False, floatfmt=".1f"),
                "",
                "![p50/p99 vs patients](benchmark.svg)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    logger.info("wrote %s", args.out / "benchmark.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
