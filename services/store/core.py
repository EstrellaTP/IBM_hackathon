"""Encrypted, pseudonymised storage for signal, episodes, answers and the audit log.

Role in the architecture (CLAUDE.md section 8): every component that persists health
data goes through this module. Design choices:

* **Encryption at rest of every health field** with Fernet (AES-128-CBC + HMAC-SHA256;
  on LinuxONE both run on the CPACF crypto instructions, see docs/vm-check.md). Only
  the pseudonymous ``patient_id``, ids and timestamps stay in clear, because queries
  need them. Signal samples, episode features and scores, severity and the patient's
  answers are only stored encrypted.
* **Pseudonymisation**: there is no table with real identities.
* **Append-only audit log**: SQLite triggers reject ``UPDATE`` and ``DELETE``, and each
  row carries a SHA-256 hash chained to the previous row, so a change made outside the
  application (e.g. by editing the file) is detected by :meth:`verify_audit_chain`.

SQLite is enough for the prototype (one writer, WAL mode); the service boundary keeps
the option of moving to PostgreSQL without touching the other services.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from services.common.schemas import (
    AuditEntry,
    EpisodeEvent,
    QuestionAnswer,
    SignalBatch,
    utcnow,
)

logger = logging.getLogger(__name__)

# First "previous hash" of the audit chain.
GENESIS_HASH = "0" * 64

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS signal_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    first_sample_t TEXT NOT NULL,
    last_sample_t TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    payload BLOB NOT NULL               -- encrypted SignalBatch JSON
);
CREATE INDEX IF NOT EXISTS idx_batches_patient ON signal_batches (patient_id, last_sample_t);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    start TEXT NOT NULL,
    payload BLOB NOT NULL               -- encrypted EpisodeEvent JSON
);
CREATE INDEX IF NOT EXISTS idx_episodes_patient ON episodes (patient_id, start);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES episodes (episode_id),
    stored_at TEXT NOT NULL,
    payload BLOB NOT NULL               -- encrypted QuestionAnswer JSON
);
CREATE INDEX IF NOT EXISTS idx_answers_episode ON answers (episode_id, id);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry TEXT NOT NULL,                -- AuditEntry JSON (ids and versions, no health data)
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""


class UnknownEpisodeError(LookupError):
    """An answer refers to an episode that does not exist."""


@dataclass(frozen=True)
class PatientSummary:
    """Per-patient counts for the clinician's patient list."""

    patient_id: str
    episodes: int
    answered: int
    last_episode_at: datetime | None


@dataclass(frozen=True)
class TimelineItem:
    """One episode with the patient's latest answer to it, if any."""

    episode: EpisodeEvent
    answer: QuestionAnswer | None


def _audit_hash(prev_hash: str, entry_json: str) -> str:
    """Hash of one audit row, chained to the previous row's hash."""
    return hashlib.sha256((prev_hash + entry_json).encode("utf-8")).hexdigest()


class EncryptedStore:
    """SQLite-backed store with field encryption and a tamper-evident audit log.

    Thread-safe for the FastAPI thread pool: a single connection guarded by a lock.

    Args:
        db_path: Database file (created if missing).
        key: Fernet key.
    """

    def __init__(self, db_path: Path, key: bytes) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(key)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._db.executescript(SCHEMA_SQL)
        logger.info("store ready at %s", db_path)

    def close(self) -> None:
        """Close the database connection."""
        self._db.close()

    # -- encryption helpers -------------------------------------------------

    def _encrypt(self, model_json: str) -> bytes:
        return self._fernet.encrypt(model_json.encode("utf-8"))

    def _decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as error:  # wrong key or tampered ciphertext
            raise ValueError("stored record cannot be decrypted with the current key") from error

    # -- writes -------------------------------------------------------------

    def add_signal_batch(self, batch: SignalBatch) -> int:
        """Store one batch of samples encrypted; return its row id."""
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO signal_batches (patient_id, received_at, first_sample_t, "
                "last_sample_t, sample_count, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    batch.patient_id,
                    utcnow().isoformat(),
                    batch.samples[0].t.isoformat(),
                    batch.samples[-1].t.isoformat(),
                    len(batch.samples),
                    self._encrypt(batch.model_dump_json()),
                ),
            )
            return int(cursor.lastrowid)

    def add_episode(self, episode: EpisodeEvent) -> None:
        """Store an episode (encrypted); storing the same id again replaces it.

        Replacing lets ``ingest-api`` store the episode first and update it with
        ``pushed_at`` once the question has been sent.
        """
        with self._lock:
            self._db.execute(
                "INSERT INTO episodes (episode_id, patient_id, start, payload) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (episode_id) DO UPDATE SET payload = excluded.payload",
                (
                    episode.episode_id,
                    episode.patient_id,
                    episode.start.isoformat(),
                    self._encrypt(episode.model_dump_json()),
                ),
            )

    def add_answer(self, answer: QuestionAnswer) -> datetime:
        """Store the patient's answer to an episode; return when it was stored.

        Several answers per episode are kept (e.g. mood first, then a safety action);
        the timeline shows the latest one.

        Raises:
            UnknownEpisodeError: If the episode does not exist.
        """
        stored_at = utcnow()
        with self._lock:
            known = self._db.execute(
                "SELECT 1 FROM episodes WHERE episode_id = ?", (answer.episode_id,)
            ).fetchone()
            if known is None:
                raise UnknownEpisodeError(answer.episode_id)
            self._db.execute(
                "INSERT INTO answers (episode_id, stored_at, payload) VALUES (?, ?, ?)",
                (answer.episode_id, stored_at.isoformat(), self._encrypt(answer.model_dump_json())),
            )
        return stored_at

    def add_audit_entry(self, entry: AuditEntry) -> str:
        """Append an audit entry to the hash chain; return its hash."""
        entry_json = entry.model_dump_json()
        with self._lock:
            row = self._db.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = row[0] if row else GENESIS_HASH
            digest = _audit_hash(prev_hash, entry_json)
            self._db.execute(
                "INSERT INTO audit_log (entry, prev_hash, hash) VALUES (?, ?, ?)",
                (entry_json, prev_hash, digest),
            )
        return digest

    # -- reads --------------------------------------------------------------

    def list_episodes(self, patient_id: str) -> list[EpisodeEvent]:
        """Return a patient's episodes, newest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM episodes WHERE patient_id = ? ORDER BY start DESC",
                (patient_id,),
            ).fetchall()
        return [EpisodeEvent.model_validate_json(self._decrypt(row[0])) for row in rows]

    def latest_answers(self, episode_ids: Iterable[str]) -> dict[str, QuestionAnswer]:
        """Return the latest answer of each episode that has one."""
        ids = list(episode_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            rows = self._db.execute(
                f"SELECT episode_id, payload FROM answers WHERE id IN ("
                f"SELECT MAX(id) FROM answers WHERE episode_id IN ({placeholders}) "
                "GROUP BY episode_id)",
                ids,
            ).fetchall()
        return {
            episode_id: QuestionAnswer.model_validate_json(self._decrypt(payload))
            for episode_id, payload in rows
        }

    def timeline(self, patient_id: str) -> list[TimelineItem]:
        """Return a patient's episodes with their latest answers, newest first."""
        episodes = self.list_episodes(patient_id)
        answers = self.latest_answers(episode.episode_id for episode in episodes)
        return [TimelineItem(episode, answers.get(episode.episode_id)) for episode in episodes]

    def list_patients(self) -> list[PatientSummary]:
        """Return every patient with episodes, most recent activity first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT e.patient_id, COUNT(*), COUNT(DISTINCT a.episode_id), MAX(e.start) "
                "FROM episodes e LEFT JOIN answers a ON a.episode_id = e.episode_id "
                "GROUP BY e.patient_id ORDER BY MAX(e.start) DESC"
            ).fetchall()
        return [
            PatientSummary(
                patient_id=patient_id,
                episodes=episodes,
                answered=answered,
                last_episode_at=datetime.fromisoformat(last) if last else None,
            )
            for patient_id, episodes, answered, last in rows
        ]

    def list_audit_entries(self, patient_id: str | None = None) -> list[AuditEntry]:
        """Return audit entries in insertion order, optionally for one patient."""
        with self._lock:
            rows = self._db.execute("SELECT entry FROM audit_log ORDER BY id").fetchall()
        entries = [AuditEntry.model_validate_json(row[0]) for row in rows]
        if patient_id is not None:
            entries = [entry for entry in entries if entry.patient_id == patient_id]
        return entries

    def verify_audit_chain(self) -> tuple[bool, int]:
        """Recompute the hash chain of the audit log.

        Returns:
            ``(valid, entries)``: whether every row matches its hash and links to the
            previous one, and how many rows were checked.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT entry, prev_hash, hash FROM audit_log ORDER BY id"
            ).fetchall()
        expected_prev = GENESIS_HASH
        for entry_json, prev_hash, digest in rows:
            if prev_hash != expected_prev or _audit_hash(prev_hash, entry_json) != digest:
                return False, len(rows)
            expected_prev = digest
        return True, len(rows)

    def signal_batch_count(self, patient_id: str) -> int:
        """Return how many batches are stored for a patient."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM signal_batches WHERE patient_id = ?", (patient_id,)
            ).fetchone()
        return int(row[0])
