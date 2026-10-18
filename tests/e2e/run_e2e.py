"""End-to-end check of the deployed vertical slice (``scripts/smoke_test.sh --e2e``).

Acts as the patient's phone and the band against a running stack, over the public
TLS gateway::

    python tests/e2e/run_e2e.py https://148.100.99.58:8443

1. Opens the question WebSocket for a fresh pseudonymous patient.
2. Sends synthetic signal (calm, then stress) in 10-second batches, fast-forward.
3. Waits for the question on the WebSocket and checks its stage timestamps.
4. Posts an answer, then reads the clinician timeline and checks the answer is there.

Only synthetic data is sent: no real health data leaves the VM. Exit code 0 on
success, 1 on failure; timings are printed for the evidence log.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import sys
import time
from datetime import datetime

import httpx
import websockets

from ml.data import synthetic
from services.common.schemas import SignalBatch, new_patient_id, utcnow
from tools.simulator.replay import schedule_batches

BATCH_SECONDS = 10
QUESTION_TIMEOUT_SECONDS = 60


def _insecure_ssl() -> ssl.SSLContext:
    """The demo gateway uses a self-signed certificate."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def _wait_for_question(socket) -> dict:
    while True:
        message = json.loads(await socket.recv())
        if message["type"] == "question":
            return message["episode"]


async def run(base_url: str) -> int:
    """Run the scenario; return a process exit code."""
    patient_id = new_patient_id()
    ws_url = base_url.replace("https://", "wss://") + f"/api/v1/patients/{patient_id}/questions"
    stream = synthetic.wesad_wrist_stream(
        duration_s=1500, periods=(synthetic.Period(1200, 1500, "stress"),), seed=7
    )
    print(f"patient={patient_id} gateway={base_url}")
    async with (
        httpx.AsyncClient(base_url=base_url, verify=False, timeout=30) as client,
        websockets.connect(ws_url, ssl=_insecure_ssl()) as socket,
    ):
        question_task = asyncio.create_task(_wait_for_question(socket))
        sent = 0
        started = time.perf_counter()
        for scheduled in schedule_batches(stream, utcnow(), BATCH_SECONDS, realtime_from_s=1e9):
            batch = SignalBatch(
                patient_id=patient_id, device="sim", sent_at=utcnow(), samples=scheduled.samples
            )
            response = await client.post(
                "/api/v1/signal-batches",
                content=batch.model_dump_json(),
                headers={"content-type": "application/json"},
            )
            response.raise_for_status()
            sent += 1
            if response.json()["episodes"] or question_task.done():
                break
        episode = await asyncio.wait_for(question_task, QUESTION_TIMEOUT_SECONDS)
        received_at = utcnow()
        print(f"batches sent={sent} in {time.perf_counter() - started:.1f} s")
        stamps = {k: datetime.fromisoformat(v) for k, v in episode["timestamps"].items() if v}
        server_ms = (stamps["inferred_at"] - stamps["ingested_at"]).total_seconds() * 1000
        push_ms = (stamps["pushed_at"] - stamps["inferred_at"]).total_seconds() * 1000
        to_phone_ms = (received_at - stamps["pushed_at"]).total_seconds() * 1000
        print(
            f"question episode={episode['episode_id']} severity={episode['severity']} "
            f"server(ingest->inference)={server_ms:.1f} ms inference->push={push_ms:.1f} ms "
            f"push->phone={to_phone_ms:.1f} ms"
        )
        answer = {
            "episode_id": episode["episode_id"],
            "activity": "work",
            "mood_1_5": 2,
            "answered_at": utcnow().isoformat(),
        }
        stored = await client.post("/api/v1/answers", json=answer)
        if stored.status_code != httpx.codes.CREATED:
            print(f"FAIL answer not stored: {stored.status_code} {stored.text}")
            return 1
        timeline = (await client.get(f"/api/v1/clinician/patients/{patient_id}/timeline")).json()
    items = timeline["items"]
    ok = (
        len(items) == 1
        and items[0]["episode"]["episode_id"] == episode["episode_id"]
        and items[0]["answer"]["mood_1_5"] == answer["mood_1_5"]
    )
    print("clinician timeline shows the answer" if ok else f"FAIL timeline: {timeline}")
    return 0 if ok else 1


def main() -> int:
    """Entry point: ``run_e2e.py <gateway base URL>``."""
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "https://localhost:8443").rstrip("/")
    try:
        return asyncio.run(run(base_url))
    except (TimeoutError, httpx.HTTPError, OSError) as error:
        print(f"FAIL {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
