r"""End-to-end check of the deployed vertical slice (``scripts/smoke_test.sh --e2e``).

Acts as the patient's phone, the band and the clinician against a running stack,
through the TLS gateway, with the access control of issue #14::

    E2E_PATIENT_USER=... E2E_PATIENT_PASSWORD=... \
    E2E_CLINICIAN_USER=... E2E_CLINICIAN_PASSWORD=... DEVICE_KEY=... \
    python -m tests.e2e.run_e2e https://148.100.99.58:8443

1. Checks that protected routes refuse missing or wrong credentials (401/403).
2. Logs in as the patient, opens their question WebSocket with the session token.
3. Sends synthetic signal (calm, then stress) with the device key, fast-forward.
4. Waits for the question, answers it with the patient token.
5. Logs in as the clinician (assigned to that patient) and finds the answer.

Use dedicated e2e accounts (``tools/create_user.py``), not the demo ones, so the demo
timeline stays clean. Only synthetic data is sent. Exit code 0 on success.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
import time
from datetime import datetime

import httpx
import websockets

from ml.data import synthetic
from services.common.schemas import SignalBatch, utcnow
from tools.device import device_headers
from tools.simulator.replay import schedule_batches

BATCH_SECONDS = 10
QUESTION_TIMEOUT_SECONDS = 60


def _ssl_context(verify: bool) -> ssl.SSLContext:
    """Verify the certificate unless the target uses the self-signed fallback."""
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


async def _wait_for_question(socket) -> dict:
    while True:
        message = json.loads(await socket.recv())
        if message["type"] == "question":
            return message["episode"]


async def _login(client: httpx.AsyncClient, user_var: str, password_var: str) -> dict:
    response = await client.post(
        "/api/v1/sessions",
        json={"username": os.environ[user_var], "password": os.environ[password_var]},
    )
    response.raise_for_status()
    return response.json()


def _bearer(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['token']}"}


async def check_refusals(client: httpx.AsyncClient, patient: dict) -> list[str]:
    """Protected routes must refuse anonymous or wrong-role callers."""
    failures = []
    expectations = [
        ("GET", "/api/v1/clinician/patients", {}, 401),
        (
            "GET",
            f"/api/v1/clinician/patients/{patient['patient_id']}/timeline",
            _bearer(patient),
            403,
        ),
        ("POST", "/api/v1/signal-batches", {"content-type": "application/json"}, 401),
        ("POST", "/api/v1/sessions", {}, 401),
    ]
    for method, path, headers, expected in expectations:
        body = {"username": "nobody", "password": "wrong"} if path.endswith("sessions") else {}
        response = await client.request(method, path, headers=headers, json=body)
        status = response.status_code
        # A signal batch without a key may be refused before validation (401) or by
        # validation of the empty body (422); both prove it was not accepted.
        ok = status == expected or (path.endswith("signal-batches") and status in (401, 422))
        print(f"  refusal {method} {path} -> {status} ({'ok' if ok else 'FAIL'})")
        if not ok:
            failures.append(path)
    return failures


async def run(base_url: str, verify: bool) -> int:
    """Run the scenario; return a process exit code."""
    stream = synthetic.wesad_wrist_stream(
        duration_s=1500, periods=(synthetic.Period(1200, 1500, "stress"),), seed=7
    )
    async with httpx.AsyncClient(base_url=base_url, verify=verify, timeout=30) as client:
        patient = await _login(client, "E2E_PATIENT_USER", "E2E_PATIENT_PASSWORD")
        patient_id = patient["patient_id"]
        print(f"patient login ok: {patient_id} gateway={base_url}")
        if await check_refusals(client, patient):
            return 1
        ws_url = (
            base_url.replace("https://", "wss://")
            + f"/api/v1/patients/{patient_id}/questions?token={patient['token']}"
        )
        async with websockets.connect(ws_url, ssl=_ssl_context(verify)) as socket:
            question_task = asyncio.create_task(_wait_for_question(socket))
            sent, started = 0, time.perf_counter()
            for scheduled in schedule_batches(stream, utcnow(), BATCH_SECONDS, realtime_from_s=1e9):
                batch = SignalBatch(
                    patient_id=patient_id, device="sim", sent_at=utcnow(), samples=scheduled.samples
                )
                response = await client.post(
                    "/api/v1/signal-batches",
                    content=batch.model_dump_json(),
                    headers=device_headers(),
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
        to_phone_ms = (received_at - stamps["pushed_at"]).total_seconds() * 1000
        print(
            f"question episode={episode['episode_id']} severity={episode['severity']} "
            f"server(ingest->inference)={server_ms:.1f} ms push->phone={to_phone_ms:.1f} ms"
        )
        answer = {
            "episode_id": episode["episode_id"],
            "activity": "work",
            "mood_1_5": 2,
            "answered_at": utcnow().isoformat(),
        }
        stored = await client.post("/api/v1/answers", json=answer, headers=_bearer(patient))
        if stored.status_code != httpx.codes.CREATED:
            print(f"FAIL answer not stored: {stored.status_code} {stored.text}")
            return 1
        clinician = await _login(client, "E2E_CLINICIAN_USER", "E2E_CLINICIAN_PASSWORD")
        timeline = (
            await client.get(
                f"/api/v1/clinician/patients/{patient_id}/timeline", headers=_bearer(clinician)
            )
        ).json()
    answered = [i for i in timeline.get("items", []) if i["answer"]]
    ok = any(i["episode"]["episode_id"] == episode["episode_id"] for i in answered)
    print("clinician timeline shows the answer" if ok else f"FAIL timeline: {timeline}")
    return 0 if ok else 1


def main() -> int:
    """Entry point: ``run_e2e <gateway base URL>`` (``E2E_INSECURE=1`` for self-signed)."""
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "https://localhost:8443").rstrip("/")
    verify = os.environ.get("E2E_INSECURE", "") != "1"
    try:
        return asyncio.run(run(base_url, verify))
    except (TimeoutError, httpx.HTTPError, OSError, KeyError) as error:
        print(f"FAIL {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
