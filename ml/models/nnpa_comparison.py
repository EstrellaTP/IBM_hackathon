"""Inference with and without the Telum Integrated Accelerator for AI (NNPA).

Runs on the LinuxONE VM (IBM z17, NNPA usable from the guest, docs/vm-check.md)::

    python3 -m ml.models.nnpa_comparison --out ml/reports

The same LightGBM model, trained on the real NHANES features, is scored by three
engines on the same rows:

* ``lightgbm``: LightGBM's own CPU inference;
* ``snapml_cpu``: IBM Snap ML with ``tree_format="compress_trees"`` (CPU);
* ``snapml_nnpa``: IBM Snap ML with ``tree_format="zdnn_tensors"``, which turns the
  trees into matrix operations executed on the NNPA through the zDNN library.

For batch sizes from one person to 10,000 it reports the median latency over repeats,
the throughput and the maximum probability difference to LightGBM (the NNPA computes
in reduced precision, so small differences are expected and reported).
"""

from __future__ import annotations

import argparse
import logging
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.models import train

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
BATCH_SIZES = (1, 10, 100, 1000, 10000)
REPEATS = 30
WARMUP_CALLS = 3


def _timed(predict, x: np.ndarray, repeats: int) -> tuple[float, np.ndarray]:
    """Median wall time in ms of ``predict(x)`` after a warm-up, and its output."""
    for _ in range(WARMUP_CALLS):
        output = predict(x)
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        output = predict(x)
        times.append((time.perf_counter() - started) * 1000)
    return statistics.median(times), np.asarray(output, dtype=np.float64)


def build_engines(model_path: Path, x_sample: np.ndarray) -> dict[str, object]:
    """Load the LightGBM text model into each engine; return predict callables."""
    from snapml import BoostingMachineClassifier

    booster = lgb.Booster(model_file=str(model_path))
    engines = {"lightgbm": lambda x: booster.predict(x)}
    for name, tree_format in (("snapml_cpu", "compress_trees"), ("snapml_nnpa", "zdnn_tensors")):
        model = BoostingMachineClassifier()
        model.import_model(str(model_path), "lightgbm", tree_format=tree_format, X=x_sample)
        selected = model.booster_.optimized_tree_format_
        if selected != tree_format:
            raise RuntimeError(f"{name}: asked for {tree_format}, Snap ML selected {selected}")
        logger.info("%s uses tree format %s", name, selected)
        engines[name] = lambda x, m=model: m.predict_proba(x, n_jobs=1)[:, 1]
    return engines


def main(argv: list[str] | None = None) -> int:
    """Train the model, time every engine and write ``nnpa_comparison.md``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="LightGBM inference with and without NNPA.")
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--out", type=Path, default=Path("ml/reports"))
    args = parser.parse_args(argv)

    table = pd.read_csv(args.processed_dir / "features_nhanes.csv")
    x_frame, y, _ = train.prepare(table)
    x_all = x_frame.fillna(x_frame.median()).to_numpy(dtype=np.float32)
    pipeline = train.make_models(len(y))["lightgbm"].fit(x_frame, y)
    booster = pipeline.named_steps["lgbmclassifier"].booster_
    rng = np.random.default_rng(train.RANDOM_STATE)
    rows = []
    with tempfile.TemporaryDirectory() as workdir:
        model_path = Path(workdir) / "nhanes_lightgbm.txt"
        booster.save_model(str(model_path))
        engines = build_engines(model_path, x_all[:1000])
        for batch in BATCH_SIZES:
            x = x_all[rng.integers(0, len(x_all), batch)]
            repeats = REPEATS if batch <= 1000 else max(5, REPEATS // 5)
            reference_ms, reference = _timed(engines["lightgbm"], x, repeats)
            for name, predict in engines.items():
                ms, output = (
                    (reference_ms, reference) if name == "lightgbm" else _timed(predict, x, repeats)
                )
                rows.append(
                    {
                        "batch": batch,
                        "engine": name,
                        "median_ms": ms,
                        "rows_per_s": batch / (ms / 1000) if ms > 0 else float("nan"),
                        "max_abs_diff_vs_lightgbm": float(np.max(np.abs(output - reference))),
                    }
                )
            logger.info("batch %d done", batch)
    results = pd.DataFrame(rows)
    wide = results.pivot(index="batch", columns="engine", values="median_ms")
    wide["nnpa_speedup_vs_snapml_cpu"] = wide["snapml_cpu"] / wide["snapml_nnpa"]
    wide["nnpa_speedup_vs_lightgbm"] = wide["lightgbm"] / wide["snapml_nnpa"]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "nnpa_comparison.md").write_text(
        "\n".join(
            [
                "# Inference with and without the IBM Z Integrated Accelerator for AI (NNPA)",
                "",
                f"Generated by `python3 -m ml.models.nnpa_comparison` on `{platform.machine()}` "
                "(IBM z17, z/VM guest, 3 vCPUs). Model: LightGBM trained on the real NHANES "
                f"features ({len(y)} people, {len(train.FEATURES)} features, "
                f"{booster.num_trees()} trees). Single-threaded scoring; median of repeated calls "
                "after warm-up. Engines: LightGBM CPU, IBM Snap ML compressed trees (CPU) and "
                "IBM Snap ML zDNN tensors (NNPA).",
                "",
                "## Median latency (ms) per batch",
                "",
                wide.reset_index().to_markdown(index=False, floatfmt=".3f"),
                "",
                "## All measurements",
                "",
                results.to_markdown(index=False, floatfmt=".4g"),
                "",
                "`max_abs_diff_vs_lightgbm`: largest probability difference against LightGBM on "
                "the same rows (the NNPA computes in reduced precision).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    logger.info("wrote %s", args.out / "nnpa_comparison.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
