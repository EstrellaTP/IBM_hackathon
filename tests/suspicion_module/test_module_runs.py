from datetime import date, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sklearn.model_selection import GroupKFold

from ml.data import synthetic
from ml.features import hourly
from ml.models import train
from services.store import api as store_api
from services.store.main import app as store_app
from services.suspicion_module import api as module_api
from services.suspicion_module.core import evidence_flags, reference_group
from services.suspicion_module.main import app as module_app
from tests.ml.test_train import _feature_table

PATIENT = "p_dec0dec0"
REFERENCE = "ml/reports/reference_ranges.json"
DAYS = 10


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_DB_PATH", str(tmp_path / "module.sqlite3"))
    monkeypatch.setenv("STORE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SUSPICION_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setenv("REFERENCE_RANGES_PATH", REFERENCE)
    table = _feature_table(60, 0.4, 11, "dep")
    x, y, groups = train.prepare(table)
    train.export_portable_model(
        "logistic", x, y, groups, tmp_path / "model", GroupKFold(5), "synthetic", {}, []
    )
    for cached in (store_api.get_store, module_api.get_settings, module_api.get_module):
        cached.cache_clear()
    store_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=store_app), base_url="http://store"
    )
    module_app.dependency_overrides[module_api.get_client] = lambda: store_client
    store = TestClient(store_app)
    activity = synthetic.depresjon_activity(days=DAYS, depressed=True, seed=2)
    hours = hourly.depresjon_hourly(activity, "condition_x")
    start = date.today() - timedelta(days=DAYS)
    store.put(
        f"/api/v1/patients/{PATIENT}/profile",
        json={
            "sex": "F",
            "age_group": "35-39",
            "device": "actiwatch",
            "recording_start": start.isoformat(),
        },
    )
    rows = hours[["day", "hour", "activity", "valid"]].to_dict("records")
    assert store.post(f"/api/v1/patients/{PATIENT}/activity-hours", json=rows).status_code == 201
    yield TestClient(module_app), start
    module_app.dependency_overrides.clear()
    for cached in (store_api.get_store, module_api.get_settings, module_api.get_module):
        cached.cache_clear()


def _request(start, days=DAYS):
    return {
        "patient_id": PATIENT,
        "suspicion": "depression",
        "period": {"from": f"{start}T00:00:00Z", "to": f"{start + timedelta(days=days)}T00:00:00Z"},
        "requested_by": "clinician_demo",
    }


def test_module_run_returns_four_metrics_with_reference_bands_and_quality(client):
    module, start = client
    response = module.post("/api/v1/module-runs", json=_request(start))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["result"] in {"compatible", "not_compatible"}
    assert 0.5 <= result["confidence"] <= 1
    names = [metric["name"] for metric in result["metrics"]]
    assert names == ["sleep", "circadian_rhythm", "daytime_activity", "heart_rate"]
    heart = result["metrics"][3]
    assert heart["available"] is False and heart["reference"] is None
    sleep = result["metrics"][0]
    assert sleep["reference"]["group"] == "F_30-39"
    assert len(sleep["patient_series"]) == result["data_quality"]["valid_days"]
    assert sum(m["is_evidence"] for m in result["metrics"]) <= 2
    audit = store_api.get_store().list_audit_entries(PATIENT)
    assert audit[-1].action == "module_run" and audit[-1].actor == "clinician_demo"


def test_too_short_recording_is_refused_with_422(client):
    module, start = client
    response = module.post("/api/v1/module-runs", json=_request(start, days=2))
    assert response.status_code == 422


def test_unknown_patient_returns_404(client):
    module, start = client
    request = _request(start) | {"patient_id": "p_0000aaaa"}
    assert module.post("/api/v1/module-runs", json=request).status_code == 404


def test_reference_group_maps_age_groups_to_nhanes_bands():
    assert reference_group("F", "35-39") == "F_30-39"
    assert reference_group("M", "20-24") == "M_18-29"
    assert reference_group("M", "70+") == "M_70+"


def test_evidence_marks_metrics_pushing_towards_the_result():
    contributions = {"rest_hours_per_day": 0.8, "ra": -0.1, "daytime_activity": 0.3}
    flags = evidence_flags(contributions, compatible=True)
    assert flags[next(iter(flags))][1] is True  # sleep supports "compatible"
    assert [m for m, (_, evidence) in flags.items() if evidence] != []
    assert all(
        not evidence for (_, evidence) in evidence_flags(contributions, False).values() if _ > 0
    )
