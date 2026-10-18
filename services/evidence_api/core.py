"""Clinician-facing reads: patient list and episode timeline with answers.

Role in the architecture (CLAUDE.md section 5.2): the clinician panel never talks to
the store directly; evidence-api reads it and records every access in the audit log
("who looked at which patient"), as required for traceability (section 11). It
returns metrics, episodes and the patient's own answers only: no generated text about
the patient (section 5.5).
"""

from __future__ import annotations

import logging

import httpx

from services.common.schemas import AuditEntry

logger = logging.getLogger(__name__)


class EvidenceReader:
    """Reads clinician views from the store and audits each access.

    Args:
        client: HTTP client for the store.
        store_url: Base URL of the store.
    """

    def __init__(self, client: httpx.AsyncClient, store_url: str) -> None:
        self._client = client
        self._store_url = store_url.rstrip("/")

    async def patients(self) -> list[dict]:
        """Patients with episodes, most recent activity first."""
        response = await self._client.get(f"{self._store_url}/api/v1/patients")
        response.raise_for_status()
        return response.json()

    async def timeline(self, patient_id: str, viewer: str = "clinician") -> dict:
        """A patient's episodes with the latest answer to each, newest first."""
        response = await self._client.get(
            f"{self._store_url}/api/v1/patients/{patient_id}/timeline"
        )
        response.raise_for_status()
        timeline = response.json()
        audit = AuditEntry(
            actor=viewer,
            action="timeline_viewed",
            patient_id=patient_id,
            detail={"episodes": len(timeline["items"])},
        )
        audit_response = await self._client.post(
            f"{self._store_url}/api/v1/audit-entries", json=audit.model_dump(mode="json")
        )
        audit_response.raise_for_status()
        return timeline
