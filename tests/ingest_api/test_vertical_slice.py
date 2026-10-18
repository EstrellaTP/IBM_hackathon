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
from fastapi import WebSocketDisconnect
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
from tests.auth_helpers import DEVICE_HEADERS, clear_auth_caches, setup_auth

PATIENT = "p_5eed0001"
OTHER_PATIENT = "p_5eed0002"
BATCH_SECONDS = 60
JSON = {"content-type": "application/json"}


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_DB_PATH", str(tmp_path / "slice.sqlite3"))
    monkeypatch.setenv("STORE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    accounts = setup_auth(monkeypatch, tmp_path, PATIENT, OTHER_PATIENT)
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
    yield TestClient(ingest_app), TestClient(evidence_app), accounts
    ingest_app.dependency_overrides.clear()
    evidence_app.dependency_overrides.clear()
    store_api.get_store.cache_clear()
    registry.get_registry.cache_clear()
    clear_auth_caches()


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
    response = client.post(
        "/api/v1/signal-batches", content=batch.model_dump_json(), headers=DEVICE_HEADERS
    )
    assert response.status_code == 202, response.text
    return response.json()["episodes"]


def test_question_reaches_the_phone_during_stress_and_the_answer_reaches_the_clinician(stack):
    ingest, evidence, accounts = stack
    # Calm, then stress (HR and EDA up, no movement) at 20-30 min, then exercise at 40-45.
    stream = synthetic.wesad_wrist_stream(duration_s=3000, seed=3)
    origin = stream.index[0]
    with ingest.websocket_connect(
        f"/api/v1/patients/{PATIENT}/questions?token={accounts.patient_token}"
    ) as phone:
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
    stored = ingest.post(
        "/api/v1/answers", content=json.dumps(answer), headers=JSON | accounts.patient
    )
    assert stored.status_code == 201

    timeline = evidence.get(
        f"/api/v1/clinician/patients/{PATIENT}/timeline", headers=accounts.clinician
    ).json()
    # The synthetic stress may also escalate to the safety protocol (issue #6), so
    # look the answered episode up by id instead of expecting a single item.
    [item] = [i for i in timeline["items"] if i["episode"]["episode_id"] == episode["episode_id"]]
    assert item["episode"]["timestamps"]["pushed_at"] is not None
    assert item["answer"]["mood_1_5"] == 2
    [summary] = evidence.get("/api/v1/clinician/patients", headers=accounts.clinician).json()
    assert summary["episodes"] >= 1 and summary["answered"] == 1

    audit = store_api.get_store().list_audit_entries(PATIENT)
    actions = {entry.action for entry in audit}
    assert {"episode_inference", "answer_stored", "timeline_viewed"} <= actions
    assert store_api.get_store().verify_audit_chain()[0]


def test_exercise_does_not_send_a_question(stack):
    ingest, _, accounts = stack
    # Calm warm-up, then only exercise (HR up with movement).
    stream = synthetic.wesad_wrist_stream(
        duration_s=1800, periods=(Period(900, 1500, "exercise"),), seed=4
    )
    episodes = [e for samples in _batches(stream) for e in _send(ingest, samples)]
    assert episodes == []


def test_answer_to_unknown_episode_returns_404(stack):
    ingest, _, accounts = stack
    answer = {"episode_id": "e_ffffffff", "mood_1_5": 3, "answered_at": utcnow().isoformat()}
    response = ingest.post(
        "/api/v1/answers", content=json.dumps(answer), headers=JSON | accounts.patient
    )
    assert response.status_code == 404


def test_phone_connecting_late_receives_the_pending_question(stack):
    ingest, _, accounts = stack
    stream = synthetic.wesad_wrist_stream(duration_s=2000, seed=3)
    detected = []
    for samples in _batches(stream):
        detected += _send(ingest, samples)
        if detected:
            break
    assert detected and detected[0]["timestamps"]["pushed_at"] is None  # no phone yet
    with ingest.websocket_connect(
        f"/api/v1/patients/{PATIENT}/questions?token={accounts.patient_token}"
    ) as phone:
        message = phone.receive_json()
    # Only the most relevant pending question is sent: an extreme one if any, else the
    # newest (issue #13).
    expected = [e for e in detected if e["severity"] == "extreme"] or detected
    assert message["episode"]["episode_id"] == expected[-1]["episode_id"]
    assert message["episode"]["timestamps"]["pushed_at"] is not None


def test_reconnection_sends_only_the_most_relevant_pending_question():
    from datetime import timedelta

    from services.common.schemas import EpisodeEvent, StageTimestamps
    from services.ingest_api.api import select_pending_question

    def episode(minutes, severity):
        at = utcnow() - timedelta(minutes=minutes)
        return EpisodeEvent(
            patient_id=PATIENT, start=at, detected_at=at, severity=severity, score=3.0,
            method="zscore", timestamps=StageTimestamps(sample_t=at),
        )  # fmt: skip

    older_extreme, newest_normal = episode(3, "extreme"), episode(1, "normal")
    assert select_pending_question([older_extreme, newest_normal]) is older_extreme
    newer_normal, old_normal = episode(1, "normal"), episode(5, "normal")
    assert select_pending_question([old_normal, newer_normal]) is newer_normal
    assert select_pending_question([]) is None


# --- access control (issue #14) -------------------------------------------------


def _first_episode(ingest):
    stream = synthetic.wesad_wrist_stream(duration_s=2000, seed=3)
    for samples in _batches(stream):
        episodes = _send(ingest, samples)
        if episodes:
            return episodes[0]
    raise AssertionError("no episode detected")


def test_signal_batches_need_the_device_key(stack):
    ingest, _, _ = stack
    batch = SignalBatch(
        patient_id=PATIENT, device="sim", sent_at=utcnow(), samples=[{"t": utcnow(), "hr": 70.0}]
    )
    for headers in (JSON, JSON | {"X-Device-Key": "wrong"}):
        response = ingest.post(
            "/api/v1/signal-batches", content=batch.model_dump_json(), headers=headers
        )
        assert response.status_code == 401


def test_question_channel_needs_the_patients_own_token(stack):
    ingest, _, accounts = stack
    base = f"/api/v1/patients/{PATIENT}/questions"
    for query, code in (
        ("", 4401),
        ("?token=garbage", 4401),
        (f"?token={accounts.other_patient_token}", 4403),
    ):
        with (
            pytest.raises(WebSocketDisconnect) as closed,
            ingest.websocket_connect(base + query) as ws,
        ):
            ws.receive_json()
        assert closed.value.code == code


def test_answers_need_a_patient_token_and_only_for_own_episodes(stack):
    ingest, _, accounts = stack
    episode = _first_episode(ingest)
    answer = json.dumps(
        {"episode_id": episode["episode_id"], "mood_1_5": 3, "answered_at": utcnow().isoformat()}
    )
    assert ingest.post("/api/v1/answers", content=answer, headers=JSON).status_code == 401
    assert (
        ingest.post(
            "/api/v1/answers", content=answer, headers=JSON | accounts.other_patient
        ).status_code
        == 403
    )
    assert (
        ingest.post(
            "/api/v1/answers", content=answer, headers=JSON | accounts.clinician
        ).status_code
        == 403
    )
    assert (
        ingest.post("/api/v1/answers", content=answer, headers=JSON | accounts.patient).status_code
        == 201
    )


def test_clinician_routes_need_an_assigned_clinician(stack):
    ingest, evidence, accounts = stack
    _first_episode(ingest)
    path = f"/api/v1/clinician/patients/{PATIENT}/timeline"
    assert evidence.get(path).status_code == 401
    assert evidence.get(path, headers=accounts.patient).status_code == 403
    assert evidence.get(path, headers=accounts.unassigned_clinician).status_code == 403
    assert evidence.get(path, headers=accounts.clinician).status_code == 200
    assert (
        evidence.get("/api/v1/clinician/patients", headers=accounts.unassigned_clinician).json()
        == []
    )


def test_patient_sees_only_their_own_timeline(stack):
    ingest, evidence, accounts = stack
    episode = _first_episode(ingest)
    mine = evidence.get("/api/v1/patients/me/timeline", headers=accounts.patient).json()
    assert mine["patient_id"] == PATIENT
    assert any(i["episode"]["episode_id"] == episode["episode_id"] for i in mine["items"])
    other = evidence.get("/api/v1/patients/me/timeline", headers=accounts.other_patient).json()
    assert other["items"] == []
    assert (
        evidence.get("/api/v1/patients/me/timeline", headers=accounts.clinician).status_code == 403
    )


def test_login_returns_a_token_and_hides_which_part_was_wrong(stack):
    _, evidence, _ = stack
    ok = evidence.post("/api/v1/sessions", json={"username": "pat", "password": "pw-pat"})
    assert ok.status_code == 201
    body = ok.json()
    assert body["role"] == "patient" and body["patient_id"] == PATIENT and body["token"]
    unknown = evidence.post("/api/v1/sessions", json={"username": "nobody", "password": "x"})
    wrong = evidence.post("/api/v1/sessions", json={"username": "pat", "password": "x"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
