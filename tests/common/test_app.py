import importlib

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

SERVICES = {
    "ingest_api": "ingest-api",
    "detector": "detector",
    "store": "store",
    "suspicion_module": "suspicion-module",
    "evidence_api": "evidence-api",
}


@pytest.mark.parametrize(("package", "name"), SERVICES.items())
def test_every_service_starts_and_reports_health(package, name, monkeypatch, tmp_path):
    monkeypatch.setenv("STORE_DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("STORE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    module = importlib.import_module(f"services.{package}.main")
    response = TestClient(module.app).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == name
    assert body["machine"] and body["byteorder"] in {"big", "little"}
