"""Test accounts and tokens for the access control of issue #14."""

import json
from dataclasses import dataclass

from services.common import auth, security

TOKEN_SECRET = "unit-test-token-secret"
DEVICE_KEY = "unit-test-device-key"
DEVICE_HEADERS = {"content-type": "application/json", "X-Device-Key": DEVICE_KEY}


@dataclass
class TestAccounts:
    """Bearer headers and query tokens for the test users."""

    patient: dict[str, str]
    patient_token: str
    other_patient: dict[str, str]
    other_patient_token: str
    clinician: dict[str, str]
    unassigned_clinician: dict[str, str]


def setup_auth(monkeypatch, tmp_path, patient_id: str, other_patient_id: str) -> TestAccounts:
    """Write a users file, set the auth environment and return tokens for each role."""
    users = [
        {"username": "pat", "role": "patient", "patient_id": patient_id},
        {"username": "other", "role": "patient", "patient_id": other_patient_id},
        {"username": "doc", "role": "clinician", "assigned_patients": [patient_id]},
        {"username": "doc2", "role": "clinician", "assigned_patients": []},
    ]
    for user in users:
        user["password_hash"] = auth.hash_password("pw-" + user["username"])
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": users}), encoding="utf-8")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", TOKEN_SECRET)
    monkeypatch.setenv("DEVICE_KEY", DEVICE_KEY)
    monkeypatch.setenv("AUTH_USERS_PATH", str(path))
    clear_auth_caches()
    directory = auth.UserDirectory(path)

    def token(name: str) -> str:
        return auth.issue_token(directory.get(name), TOKEN_SECRET)[0]

    def bearer(name: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token(name)}"}

    return TestAccounts(
        patient=bearer("pat"),
        patient_token=token("pat"),
        other_patient=bearer("other"),
        other_patient_token=token("other"),
        clinician=bearer("doc"),
        unassigned_clinician=bearer("doc2"),
    )


def clear_auth_caches() -> None:
    """Forget cached settings and users between tests."""
    security.get_auth_settings.cache_clear()
    security.get_users.cache_clear()
