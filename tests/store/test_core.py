import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from services.common.schemas import (
    AuditEntry,
    DetectionMethod,
    EpisodeEvent,
    QuestionAnswer,
    Sample,
    Severity,
    SignalBatch,
    StageTimestamps,
)
from services.store.core import EncryptedStore, UnknownEpisodeError
from services.store.settings import MissingSettingError, load_settings

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
PATIENT = "p_0a1b2c3d"
SECRET_TEXT = "walking-the-dog-xyz"


@pytest.fixture
def store(tmp_path):
    db = EncryptedStore(tmp_path / "holter.sqlite3", Fernet.generate_key())
    yield db
    db.close()


def _episode(minutes: int = 0, severity: Severity = Severity.NORMAL) -> EpisodeEvent:
    start = T0 + timedelta(minutes=minutes)
    return EpisodeEvent(
        patient_id=PATIENT,
        start=start,
        detected_at=start + timedelta(seconds=61),
        severity=severity,
        score=3.4,
        method=DetectionMethod.ZSCORE,
        features={"hr_z": 3.4, "acc_mag_z": 0.1},
        timestamps=StageTimestamps(sample_t=start + timedelta(seconds=60)),
    )


def _answer(episode_id: str, mood: int = 2) -> QuestionAnswer:
    return QuestionAnswer(
        episode_id=episode_id,
        activity="other",
        activity_text=SECRET_TEXT,
        mood_1_5=mood,
        answered_at=T0 + timedelta(minutes=2),
    )


def test_sensitive_fields_are_not_stored_in_clear(store, tmp_path):
    episode = _episode()
    store.add_episode(episode)
    store.add_answer(_answer(episode.episode_id))
    batch = SignalBatch(
        patient_id=PATIENT, device="sim", sent_at=T0, samples=[Sample(t=T0, hr=123.456, eda=0.789)]
    )
    store.add_signal_batch(batch)
    raw = (tmp_path / "holter.sqlite3").read_bytes() + b"".join(
        p.read_bytes() for p in tmp_path.glob("holter.sqlite3-*")
    )
    for clear_value in (SECRET_TEXT.encode(), b"123.456", b"0.789", b"hr_z", b"extreme", b"mood"):
        assert clear_value not in raw


def test_timeline_returns_episodes_newest_first_with_latest_answer(store):
    first, second = _episode(0), _episode(30)
    store.add_episode(first)
    store.add_episode(second)
    store.add_answer(_answer(first.episode_id, mood=2))
    store.add_answer(_answer(first.episode_id, mood=4))
    items = store.timeline(PATIENT)
    assert [i.episode.episode_id for i in items] == [second.episode_id, first.episode_id]
    assert items[0].answer is None
    assert items[1].answer.mood_1_5 == 4


def test_answer_to_unknown_episode_is_rejected(store):
    with pytest.raises(UnknownEpisodeError):
        store.add_answer(_answer("e_ffffffff"))


def test_storing_an_episode_again_updates_it(store):
    episode = _episode()
    store.add_episode(episode)
    pushed = episode.model_copy(deep=True)
    pushed.timestamps.pushed_at = T0 + timedelta(seconds=62)
    store.add_episode(pushed)
    [stored] = store.list_episodes(PATIENT)
    assert stored.timestamps.pushed_at == pushed.timestamps.pushed_at


def test_patient_summary_counts_episodes_and_answers(store):
    first, second = _episode(0), _episode(30, Severity.EXTREME)
    store.add_episode(first)
    store.add_episode(second)
    store.add_answer(_answer(first.episode_id))
    [summary] = store.list_patients()
    assert (summary.patient_id, summary.episodes, summary.answered) == (PATIENT, 2, 1)
    assert summary.last_episode_at == second.start


def _audit(action: str = "episode_inference") -> AuditEntry:
    return AuditEntry(actor="detector", action=action, patient_id=PATIENT, model_version="z1")


def test_audit_log_rejects_update_and_delete(store, tmp_path):
    store.add_audit_entry(_audit())
    raw = sqlite3.connect(tmp_path / "holter.sqlite3")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        raw.execute("UPDATE audit_log SET entry = '{}'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        raw.execute("DELETE FROM audit_log")
    raw.close()


def test_audit_chain_detects_tampering_outside_the_application(store, tmp_path):
    for action in ("episode_inference", "answer_stored", "module_run"):
        store.add_audit_entry(_audit(action))
    assert store.verify_audit_chain() == (True, 3)
    # An attacker with file access drops the trigger and rewrites history.
    raw = sqlite3.connect(tmp_path / "holter.sqlite3", isolation_level=None)
    raw.execute("DROP TRIGGER audit_log_no_update")
    raw.execute(
        "UPDATE audit_log SET entry = replace(entry, 'answer_stored', 'nothing') WHERE id = 2"
    )
    raw.close()
    assert store.verify_audit_chain() == (False, 3)


def test_store_cannot_be_read_with_another_key(tmp_path):
    first = EncryptedStore(tmp_path / "db.sqlite3", Fernet.generate_key())
    first.add_episode(_episode())
    first.close()
    second = EncryptedStore(tmp_path / "db.sqlite3", Fernet.generate_key())
    with pytest.raises(ValueError, match="cannot be decrypted"):
        second.list_episodes(PATIENT)
    second.close()


def test_settings_refuse_to_run_without_an_encryption_key():
    with pytest.raises(MissingSettingError):
        load_settings({"STORE_DB_PATH": "/tmp/x.sqlite3"})


def _post(client, path, model):
    return client.post(path, content=model.model_dump_json(), headers=JSON)


JSON = {"content-type": "application/json"}


def test_api_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_DB_PATH", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("STORE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    from services.store import api
    from services.store.main import app

    api.get_store.cache_clear()
    client = TestClient(app)
    episode = _episode()
    assert _post(client, "/api/v1/episodes", episode).status_code == 201
    answer = _answer(episode.episode_id)
    assert _post(client, "/api/v1/answers", answer).status_code == 201
    assert _post(client, "/api/v1/answers", _answer("e_ffffffff")).status_code == 404
    timeline = client.get(f"/api/v1/patients/{PATIENT}/timeline").json()
    assert timeline["items"][0]["answer"]["activity_text"] == SECRET_TEXT
    assert _post(client, "/api/v1/audit-entries", _audit()).status_code == 201
    assert client.get("/api/v1/audit-entries/verification").json() == {"valid": True, "entries": 1}
    assert client.get("/api/v1/episodes", params={"patient_id": "bad"}).status_code == 422
    api.get_store.cache_clear()
