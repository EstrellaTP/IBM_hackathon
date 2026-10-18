"""Cross-architecture check: same input, same prediction on x86 and s390x.

Run the same command on the laptop (little-endian) and on the VM (big-endian) and
compare the printed digests::

    python -m ml.models.endianness_check --artifacts DIR --out result.json

It scores a fixed, seeded set of synthetic feature rows (no health data) with:

1. the deployed portable model (``depression_model.json``), and
2. a LightGBM model trained on seeded synthetic data and saved/loaded as text, which
   checks LightGBM's own parsing and tree evaluation across byte orders.

Predictions are written with ``float.hex()`` so equality is exact, not rounded.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np

from ml.models import train
from ml.models.predict import load_model

ROWS = 50
SEED = 2026


def fixed_rows() -> list[dict[str, float]]:
    """Seeded synthetic feature rows (same on every machine)."""
    rng = np.random.default_rng(SEED)
    return [
        {
            name: float(value)
            for name, value in zip(
                train.FEATURES, rng.normal(0, 1, len(train.FEATURES)), strict=True
            )
        }
        for _ in range(ROWS)
    ]


def synthetic_booster(model_path: Path) -> lgb.Booster:
    """Load the LightGBM text model at ``model_path``, training it first if missing."""
    if not model_path.exists():
        rng = np.random.default_rng(SEED)
        x = rng.normal(0, 1, (500, len(train.FEATURES)))
        y = (x[:, 0] + 0.5 * x[:, 1] + rng.normal(0, 1, 500) > 0).astype(int)
        booster = lgb.train(
            {"objective": "binary", "verbose": -1, "num_leaves": 7, "seed": SEED},
            lgb.Dataset(x, y),
            num_boost_round=50,
        )
        booster.save_model(str(model_path))
    return lgb.Booster(model_file=str(model_path))


def main(argv: list[str] | None = None) -> int:
    """Score the fixed rows and write the exact results as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--artifacts", type=Path, required=True, help="deployed model dir")
    parser.add_argument(
        "--lightgbm-text",
        type=Path,
        required=True,
        help="synthetic LightGBM text model (created if missing)",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = fixed_rows()
    model = load_model(args.artifacts)
    deployed = [model.predict(row).probability for row in rows]
    booster = synthetic_booster(args.lightgbm_text)
    matrix = np.asarray([[row[name] for name in train.FEATURES] for row in rows])
    tree = booster.predict(matrix).tolist()
    result = {
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
        "model_version": model.version,
        "deployed_probabilities": [value.hex() for value in deployed],
        "lightgbm_text_probabilities": [value.hex() for value in tree],
    }
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"{result['machine']} {result['byteorder']}-endian: {ROWS} rows scored -> {args.out}")
    return 0


def compare(left: Path, right: Path) -> dict:
    """Compare two result files; return max absolute differences."""
    a, b = (json.loads(path.read_text(encoding="utf-8")) for path in (left, right))
    differences = {}
    for key in ("deployed_probabilities", "lightgbm_text_probabilities"):
        values_a = np.array([float.fromhex(v) for v in a[key]])
        values_b = np.array([float.fromhex(v) for v in b[key]])
        differences[key] = float(np.max(np.abs(values_a - values_b)))
    return {
        "left": f"{a['machine']} {a['byteorder']}",
        "right": f"{b['machine']} {b['byteorder']}",
        **differences,
    }


if __name__ == "__main__":
    sys.exit(main())
