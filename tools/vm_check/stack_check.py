"""Functional check of the Python stack on the VM (task F0-BE-02).

Importing a library on s390x is not enough: compiled extensions can load and still
compute wrong results on a big-endian machine. This script exercises each library
on a tiny synthetic problem and prints versions, timings and the results, so the
output can be kept as evidence::

    ~/venv-holter/bin/python tools/vm_check/stack_check.py > docs/screenshots/vm_python_stack.txt
"""

from __future__ import annotations

import platform
import sys
import time
from importlib.metadata import version

# Small synthetic classification problem: big enough to fit the models, small
# enough to run in seconds.
N_SAMPLES = 2_000
N_FEATURES = 8
RANDOM_STATE = 0


def _timed(label: str, func) -> object:
    """Run ``func``, print how long it took and return its result."""
    started = time.perf_counter()
    result = func()
    print(f"{label:<44} {time.perf_counter() - started:7.3f} s")
    return result


def main() -> int:
    """Run all checks; return 0 if every check passes."""
    print(f"machine={platform.machine()} byteorder={sys.byteorder} python={sys.version.split()[0]}")
    packages = [
        "numpy", "pandas", "scipy", "scikit-learn", "lightgbm", "shap",
        "fastapi", "uvicorn", "pydantic", "cryptography", "httpx",
    ]  # fmt: skip
    for package in packages:
        try:
            print(f"  {package}=={version(package)}")
        except Exception as error:  # noqa: BLE001 - report any missing package
            print(f"  {package}: NOT INSTALLED ({error})")

    import numpy as np
    from sklearn.datasets import make_classification
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    features, target = make_classification(
        n_samples=N_SAMPLES, n_features=N_FEATURES, random_state=RANDOM_STATE
    )
    train, test = slice(0, 1500), slice(1500, None)
    print(f"numpy BLAS: {np.show_config(mode='dicts')['Build Dependencies']['blas']['name']}")

    checks = {}
    logistic = _timed(
        "fit LogisticRegression",
        lambda: LogisticRegression(max_iter=1000).fit(features[train], target[train]),
    )
    forest = _timed(
        "fit RandomForest (100 trees)",
        lambda: RandomForestClassifier(random_state=RANDOM_STATE).fit(
            features[train], target[train]
        ),
    )
    import lightgbm as lgb

    booster = _timed(
        "fit LightGBM (100 rounds)",
        lambda: lgb.LGBMClassifier(random_state=RANDOM_STATE, verbose=-1).fit(
            features[train], target[train]
        ),
    )
    for name, model in (("logistic", logistic), ("forest", forest), ("lightgbm", booster)):
        auc = roc_auc_score(target[test], model.predict_proba(features[test])[:, 1])
        print(f"  AUC {name:<10} {auc:.4f}")
        checks[f"auc_{name}"] = auc > 0.8

    import shap

    explanation = _timed(
        "SHAP TreeExplainer on LightGBM (100 rows)",
        lambda: shap.TreeExplainer(booster).shap_values(features[test][:100]),
    )
    values = np.asarray(explanation)
    # Additivity: SHAP values + expected value must equal the raw model output.
    raw = booster.predict(features[test][:100], raw_score=True)
    expected = shap.TreeExplainer(booster).expected_value
    additivity_error = float(np.max(np.abs(values.sum(axis=1) + expected - raw)))
    print(f"  SHAP additivity max error {additivity_error:.2e}")
    checks["shap_additivity"] = additivity_error < 1e-6

    from cryptography.fernet import Fernet
    from cryptography.hazmat.backends.openssl.backend import backend

    token_key = Fernet.generate_key()
    cipher = Fernet(token_key)
    payload = b'{"hr": 92.0}' * 1000
    roundtrip = _timed(
        "Fernet encrypt+decrypt 12 kB x 1000",
        lambda: all(cipher.decrypt(cipher.encrypt(payload)) == payload for _ in range(1000)),
    )
    print(f"  cryptography backend: {backend.openssl_version_text()}")
    checks["fernet_roundtrip"] = bool(roundtrip)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    response = _timed("FastAPI TestClient GET /health", lambda: TestClient(app).get("/health"))
    checks["fastapi"] = response.json() == {"status": "ok"}

    for name, passed in checks.items():
        print(f"CHECK {name:<18} {'PASS' if passed else 'FAIL'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
