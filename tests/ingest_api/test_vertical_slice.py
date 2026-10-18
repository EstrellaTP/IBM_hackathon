"""In-process vertical slice: signal -> detector -> question -> answer -> clinician.

The real store, detector, ingest-api and evidence-api apps are wired together with
httpx ASGI transports (no network), so this test exercises the same code paths as
the deployed stack.
"""

import json
from datetime import datetime

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from ml.data import loaders, synthetic
from ml.data.synthetic import Period
from services.common.schemas import SignalBatch, utcnow
from services.detector import registry
from services.detector.main import app as detector_app
from services.evidence_api.api import get_reader
from services.evidence_api.core import EvidenceReader
from services.evidence_api.main import app as evidence_app
from services.ingest_api.api import get_pipeline
from services.ingest_api.core import IngestPipeline, QuestionHub
from services.ingest_api.main import app as ingest_app
from services.store import api as store_api
from services.store.main import app as store_app

PATIENT = "p_5eed0001"
BATCH_SECONDS = 60
JSON = {"content-type": "application/json"}


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_DB_PATH", str(tmp_path / "slice.sqlite3"))
    monkeypatch.setenv("STORE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    store_api.get_store.cache_clear()
    registry.get_registry.cache_clear()
    internal = httpx.AsyncClient(
        mounts={
            "http://detector": httpx.ASGITransport(app=detector_app),
            "http://store": httpx.ASGITransport(app=store_app),
        }
    )
    pipeline = IngestPipeline(internal, "http://detector", "http://store", QuestionHub())
    ingest_app.dependency_overrides[get_pipeline] = lambda: pipeline
    evidence_app.dependency_overrides[get_reader] = lambda: EvidenceReader(internal, "http://store")
    yield TestClient(ingest_app), TestClient(evidence_app)
    ingest_app.dependency_overrides.clear()
    evidence_app.dependency_overrides.clear()
    store_api.get_store.cache_clear()
    registry.get_registry.cache_clear()


def _batches(stream):
    samples = loaders.stream_to_samples(stream)
    start = samples[0].t
    batch, batch_end = [], BATCH_SECONDS
    for sample in samples:
        if (sample.t - start).total_seconds() >= batch_end:
            yield batch
            batch, batch_end = [], batch_end + BATCH_SECONDS
        batch.append(sample)
    if batch:
        yield batch


def _send(client, samples):
    batch = SignalBatch(patient_id=PATIENT, device="sim", sent_at=utcnow(), samples=samples)
    response = client.post("/api/v1/signal-batches", content=batch.model_dump_json(), headers=JSON)
    assert response.status_code == 202, response.text
    return response.json()["episodes"]


def test_question_reaches_the_phone_during_stress_and_the_answer_reaches_the_clinician(stack):
    ingest, evidence = stack
    # Calm, then stress (HR and EDA up, no movement) at 20-30 min, then exercise at 40-45.
    stream = synthetic.wesad_wrist_stream(duration_s=3000, seed=3)
    origin = stream.index[0]
    with ingest.websocket_connect(f"/api/v1/patients/{PATIENT}/questions") as phone:
        detected = []
        for samples in _batches(stream):
            detected += _send(ingest, samples)
            if detected:
                break
        message = phone.receive_json()
    assert message["type"] == "question"
    episode = message["episode"]
    assert detected[0]["episode_id"] == episode["episode_id"]
    start_s = (datetime.fromisoformat(episode["start"]) - origin).total_seconds()
    assert 1200 - BATCH_SECONDS <= start_s < 1800  # inside the stress period
    stamps = episode["timestamps"]
    assert stamps["ingested_at"] and stamps["inferred_at"] and stamps["pushed_at"]

    answer = {
        "episode_id": episode["episode_id"],
        "activity": "work",
        "activity_text": "presentation",
        "mood_1_5": 2,
        "answered_at": utcnow().isoformat(),
    }
    stored = ingest.post("/api/v1/answers", content=json.dumps(answer), headers=JSON)
    assert stored.status_code == 201

    timeline = evidence.get(f"/api/v1/clinician/patients/{PATIENT}/timeline").json()
    [item] = timeline["items"]
    assert item["episode"]["episode_id"] == episode["episode_id"]
    assert item["episode"]["timestamps"]["pushed_at"] is not None
    assert item["answer"]["mood_1_5"] == 2
    [summary] = evidence.get("/api/v1/clinician/patients").json()
    assert (summary["episodes"], summary["answered"]) == (1, 1)

    audit = store_api.get_store().list_audit_entries(PATIENT)
    actions = {entry.action for entry in audit}
    assert {"episode_inference", "answer_stored", "timeline_viewed"} <= actions
    assert store_api.get_store().verify_audit_chain()[0]


def test_exercise_does_not_send_a_question(stack):
    ingest, _ = stack
    # Calm warm-up, then only exercise (HR up with movement).
    stream = synthetic.wesad_wrist_stream(
        duration_s=1800, periods=(Period(900, 1500, "exercise"),), seed=4
    )
    episodes = [e for samples in _batches(stream) for e in _send(ingest, samples)]
    assert episodes == []


def test_answer_to_unknown_episode_returns_404(stack):
    ingest, _ = stack
    answer = {"episode_id": "e_ffffffff", "mood_1_5": 3, "answered_at": utcnow().isoformat()}
    response = ingest.post("/api/v1/answers", content=json.dumps(answer), headers=JSON)
    assert response.status_code == 404


def test_phone_connecting_late_receives_the_pending_question(stack):
    ingest, _ = stack
    stream = synthetic.wesad_wrist_stream(duration_s=2000, seed=3)
    detected = []
    for samples in _batches(stream):
        detected += _send(ingest, samples)
        if detected:
            break
    assert detected and detected[0]["timestamps"]["pushed_at"] is None  # no phone yet
    with ingest.websocket_connect(f"/api/v1/patients/{PATIENT}/questions") as phone:
        message = phone.receive_json()
    assert message["episode"]["episode_id"] == detected[0]["episode_id"]
    assert message["episode"]["timestamps"]["pushed_at"] is not None
