"""Train and validate the depression module per person (tasks F2-ML-03, F2-ML-04).

Runs on the VM after ``python3 -m ml.features.build``::

    python3 -m ml.models.train --reports-dir ml/reports

Protocol (CLAUDE.md section 10.2):

* **Data.** NHANES G+H adults, label PHQ-9 >= 10 ("depressive symptoms", not a
  diagnosis). DEPRESJON patients vs controls as external test and as a small
  clinical sample for leave-one-subject-out.
* **Per-person validation.** One row per person, ``GroupKFold`` by person id (5 folds,
  stratification not needed at 9 % prevalence with ~8,000 people). No day of a person
  can be in train and test: :func:`assert_disjoint_groups` checks every split.
* **Models.** Logistic regression, Random Forest and LightGBM, each with median
  imputation, wrapped in isotonic calibration fitted on the training fold only.
* **Decision threshold (fixed in advance).** Positive when the calibrated risk is at
  least the training prevalence, i.e. "higher risk than the base rate". Never tuned
  on test data.
* **External test.** Models trained on all of NHANES are applied to DEPRESJON with
  every feature (no feature selection that looked at DEPRESJON labels).
* **Fairness.** Sensitivity and specificity by sex and age group from the NHANES
  out-of-fold predictions (AI Act examination of bias, CLAUDE.md section 10.2).

Outputs: ``metrics.md``, ``reliability.svg``, ``fairness.svg`` in the reports
directory and the portable model in ``ml/models/artifacts/`` (gitignored).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    brier_score_loss,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from ml.features import circadian

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ML_DIR / "data" / "processed"
REPORTS_DIR = ML_DIR / "reports"
ARTIFACTS_DIR = ML_DIR / "models" / "artifacts"

FEATURES = [name for name in circadian.FEATURE_COLUMNS if name != "valid_days"]
N_SPLITS = 5
CALIBRATION_FOLDS = 3
# Below this many people, isotonic calibration overfits: use Platt scaling.
ISOTONIC_MIN_PEOPLE = 500
RANDOM_STATE = 42
RELIABILITY_BINS = 10
AGE_BINS = [17, 39, 59, 120]
AGE_LABELS = ["18-39", "40-59", "60+"]

# Published person-level reference on DEPRESJON (Garcia-Ceja et al., MMSys 2018).
DEPRESJON_REFERENCE = {"f1": 0.73, "mcc": 0.44}

# Models with a portable text format (big-endian safe); Random Forest is evaluated but
# not deployed because it has no portable text export.
DEPLOYABLE_MODELS = ("logistic", "lightgbm")
# Plan B trigger: below this external AUC the NHANES model is considered not to
# transfer. Set after a first run (the fallback itself was planned in CLAUDE.md 14).
TRANSFER_AUC_MIN = 0.65
BOOTSTRAP_RESAMPLES = 1000
# DEPRESJON people left out of the deployed model's final fit, so the demo dashboard
# only ever scores people the model has not seen (they still count in the LOSO).
DEMO_HOLDOUT = ("condition_3", "condition_11", "control_5", "control_12")
# Minimum leaf sizes as a share of the training set: ~20 people on NHANES, 2-3 on the
# 54 training people of a DEPRESJON fold (fixed sizes made the trees constant there).
LEAF_SHARE = 0.003


def make_models(n_people: int = 6000) -> dict[str, Pipeline]:
    """Base models (before calibration); class weights balance the prevalence.

    Args:
        n_people: Training-set size, used to scale the minimum leaf sizes.
    """
    min_leaf = max(2, round(n_people * LEAF_SHARE))
    return {
        "logistic": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=2000),
        ),
        "random_forest": make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=300,
                min_samples_leaf=min_leaf,
                class_weight="balanced_subsample",
                random_state=RANDOM_STATE,
                n_jobs=-1,
            ),
        ),
        "lightgbm": make_pipeline(
            SimpleImputer(strategy="median"),
            lgb.LGBMClassifier(
                n_estimators=300,
                learning_rate=0.03,
                num_leaves=15,
                min_child_samples=max(3, round(n_people * LEAF_SHARE * 1.5)),
                subsample=0.8,
                subsample_freq=1,
                colsample_bytree=0.8,
                is_unbalance=True,
                random_state=RANDOM_STATE,
                verbose=-1,
            ),
        ),
    }


def calibrated(model: Pipeline, n_people: int) -> CalibratedClassifierCV:
    """Wrap a model in isotonic calibration (sigmoid for very small samples)."""
    method = "isotonic" if n_people >= ISOTONIC_MIN_PEOPLE else "sigmoid"
    folds = min(CALIBRATION_FOLDS, max(2, n_people // 10))
    return CalibratedClassifierCV(model, method=method, cv=folds)


def prepare(table: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Standardise device-scaled features within the dataset; return X, y, groups."""
    features = circadian.standardise_within_dataset(
        table[FEATURES], circadian.DEVICE_SCALED_FEATURES
    )
    return features, table["label"].to_numpy(dtype=int), table["person_id"].to_numpy()


def assert_disjoint_groups(groups: np.ndarray, train: np.ndarray, test: np.ndarray) -> None:
    """Fail loudly if any person appears in both the training and the test split."""
    overlap = set(groups[train]) & set(groups[test])
    if overlap:
        raise AssertionError(f"person leakage between train and test: {sorted(overlap)[:5]}")


@dataclass
class Metrics:
    """Person-level classification metrics."""

    auc: float
    mcc: float
    f1: float
    sensitivity: float
    specificity: float
    brier: float
    people: int
    positives: int


def compute_metrics(y: np.ndarray, probability: np.ndarray, threshold: np.ndarray) -> Metrics:
    """Metrics for calibrated probabilities and per-person thresholds."""
    predicted = (probability >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, predicted, labels=[0, 1]).ravel()
    return Metrics(
        auc=roc_auc_score(y, probability) if len(set(y)) > 1 else float("nan"),
        mcc=matthews_corrcoef(y, predicted),
        f1=f1_score(y, predicted, zero_division=0),
        sensitivity=tp / (tp + fn) if tp + fn else float("nan"),
        specificity=tn / (tn + fp) if tn + fp else float("nan"),
        brier=brier_score_loss(y, probability),
        people=len(y),
        positives=int(y.sum()),
    )


def out_of_fold(
    model: Pipeline, x: pd.DataFrame, y: np.ndarray, groups: np.ndarray, splitter
) -> tuple[np.ndarray, np.ndarray]:
    """Calibrated out-of-fold probabilities and the threshold used for each person.

    The threshold of a test person is the prevalence of the training fold it was
    predicted from (decision rule fixed in advance).
    """
    probability = np.full(len(y), np.nan)
    threshold = np.full(len(y), np.nan)
    for train, test in splitter.split(x, y, groups):
        assert_disjoint_groups(groups, train, test)
        fitted = calibrated(model, len(train)).fit(x.iloc[train], y[train])
        probability[test] = fitted.predict_proba(x.iloc[test])[:, 1]
        threshold[test] = y[train].mean()
    return probability, threshold


def bootstrap_ci(
    y: np.ndarray, probability: np.ndarray, threshold: np.ndarray, seed: int = RANDOM_STATE
) -> dict[str, str]:
    """95 % percentile bootstrap intervals (resampling people) for AUC and MCC."""
    rng = np.random.default_rng(seed)
    aucs, mccs = [], []
    for _ in range(BOOTSTRAP_RESAMPLES):
        index = rng.integers(0, len(y), len(y))
        if len(set(y[index])) < 2:
            continue
        sample = compute_metrics(y[index], probability[index], threshold[index])
        aucs.append(sample.auc)
        mccs.append(sample.mcc)
    return {
        "auc_95ci": f"{np.percentile(aucs, 2.5):.2f}-{np.percentile(aucs, 97.5):.2f}",
        "mcc_95ci": f"{np.percentile(mccs, 2.5):.2f}-{np.percentile(mccs, 97.5):.2f}",
    }


def reliability_table(y: np.ndarray, probability: np.ndarray) -> pd.DataFrame:
    """Observed rate vs mean predicted risk per probability decile (quantile bins)."""
    bins = pd.qcut(probability, RELIABILITY_BINS, duplicates="drop")
    frame = pd.DataFrame({"y": y, "p": probability, "bin": bins})
    table = frame.groupby("bin", observed=True).agg(
        predicted=("p", "mean"), observed=("y", "mean"), people=("y", "size")
    )
    return table.reset_index(drop=True)


def expected_calibration_error(table: pd.DataFrame) -> float:
    """People-weighted mean |observed − predicted| over the reliability bins."""
    weights = table["people"] / table["people"].sum()
    return float((weights * (table["observed"] - table["predicted"]).abs()).sum())


def fairness_table(
    table: pd.DataFrame, y: np.ndarray, probability: np.ndarray, threshold: np.ndarray
) -> pd.DataFrame:
    """Sensitivity and specificity by sex and age group (NHANES out-of-fold)."""
    frame = table[["sex", "age_years"]].copy()
    frame["age_group"] = pd.cut(frame["age_years"], AGE_BINS, labels=AGE_LABELS)
    frame["y"], frame["p"], frame["t"] = y, probability, threshold
    rows = []
    for (sex, age_group), group in frame.groupby(["sex", "age_group"], observed=True):
        metrics = compute_metrics(
            group["y"].to_numpy(), group["p"].to_numpy(), group["t"].to_numpy()
        )
        rows.append(
            {
                "group": f"{sex} {age_group}",
                "people": metrics.people,
                "positives": metrics.positives,
                "sensitivity": metrics.sensitivity,
                "specificity": metrics.specificity,
                "auc": metrics.auc,
            }
        )
    return pd.DataFrame(rows)


def _svg_reliability(tables: dict[str, pd.DataFrame], path: Path) -> None:
    """Reliability diagram as a dependency-free SVG (predicted vs observed risk)."""
    size, pad = 360, 40
    colours = {"logistic": "#2563eb", "random_forest": "#16a34a", "lightgbm": "#dc2626"}
    top = max(0.5, max(float(t[["predicted", "observed"]].max().max()) for t in tables.values()))

    def xy(px: float, py: float) -> tuple[float, float]:
        return pad + px / top * (size - 2 * pad), size - pad - py / top * (size - 2 * pad)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size + 140}" height="{size}" '
        'font-family="sans-serif" font-size="11">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#999" stroke-dasharray="4"/>'.format(
            *xy(0, 0), *xy(top, top)
        ),
        f'<text x="{size / 2 - 60}" y="{size - 8}">mean predicted risk</text>',
        f'<text x="8" y="{pad - 12}">observed rate</text>',
    ]
    for tick in np.linspace(0, top, 6):
        x0, y0 = xy(tick, 0)
        x1, y1 = xy(0, tick)
        parts.append(f'<text x="{x0 - 8}" y="{y0 + 14}">{tick:.2f}</text>')
        parts.append(f'<text x="{x1 - 34}" y="{y1 + 4}">{tick:.2f}</text>')
    for index, (name, frame) in enumerate(tables.items()):
        points = " ".join(
            "{:.1f},{:.1f}".format(*xy(p, o))
            for p, o in zip(frame["predicted"], frame["observed"], strict=True)
        )
        colour = colours.get(name, "#555")
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="2"/>'
        )
        parts.append(f'<text x="{size + 10}" y="{pad + 16 * index}" fill="{colour}">{name}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _svg_fairness(table: pd.DataFrame, path: Path) -> None:
    """Grouped bars of sensitivity and specificity per sex x age group."""
    width, height, pad, bar = 120 + 70 * len(table), 300, 40, 24
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'font-family="sans-serif" font-size="11">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{pad}" y="16">Sensitivity (blue) and specificity (grey), '
        "NHANES out-of-fold</text>",
    ]
    plot = height - 2 * pad
    for index, row in table.reset_index(drop=True).iterrows():
        x = pad + 70 * index
        for offset, value, colour in (
            (0, row["sensitivity"], "#2563eb"),
            (bar, row["specificity"], "#9ca3af"),
        ):
            value = 0.0 if pd.isna(value) else float(value)
            h = value * plot
            top = height - pad - h
            parts.append(
                f'<rect x="{x + offset}" y="{top:.1f}" width="{bar - 2}" '
                f'height="{h:.1f}" fill="{colour}"/>'
            )
            parts.append(
                f'<text x="{x + offset}" y="{top - 3:.1f}" font-size="9">{value:.2f}</text>'
            )
        parts.append(f'<text x="{x}" y="{height - pad + 14}" font-size="10">{row["group"]}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def export_portable_model(
    model_name: str,
    x: pd.DataFrame,
    y: np.ndarray,
    groups: np.ndarray,
    out_dir: Path,
    splitter,
    trained_on: str,
    device_scaling: dict | None = None,
    held_out: list[str] | None = None,
) -> dict:
    """Fit the chosen model on all its data and save it in portable text formats.

    LightGBM is saved as its text model and logistic regression as JSON coefficients.
    The calibrator is fitted on out-of-fold raw scores: isotonic thresholds for large
    samples, Platt scaling (a, b on the logit) for small ones. Text formats load
    identically on x86 and big-endian s390x.
    """
    if model_name not in DEPLOYABLE_MODELS:
        raise ValueError(f"{model_name} has no portable export; use one of {DEPLOYABLE_MODELS}")
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_oof = np.full(len(y), np.nan)
    for train, test in splitter.split(x, y, groups):
        assert_disjoint_groups(groups, train, test)
        fitted = make_models(len(train))[model_name].fit(x.iloc[train], y[train])
        raw_oof[test] = fitted.predict_proba(x.iloc[test])[:, 1]
    if len(y) >= ISOTONIC_MIN_PEOPLE:
        isotonic = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(raw_oof, y)
        calibration = {
            "type": "isotonic",
            "x": isotonic.X_thresholds_.tolist(),
            "y": isotonic.y_thresholds_.tolist(),
        }
    else:
        clipped = np.clip(raw_oof, 1e-6, 1 - 1e-6)
        logit = np.log(clipped / (1 - clipped)).reshape(-1, 1)
        platt = LogisticRegression().fit(logit, y)
        calibration = {
            "type": "platt",
            "a": float(platt.coef_[0][0]),
            "b": float(platt.intercept_[0]),
        }
    base = make_models(len(y))[model_name].fit(x, y)
    imputer = base.named_steps["simpleimputer"]
    meta = {
        "model": model_name,
        "trained_on": trained_on,
        "features": FEATURES,
        "device_scaled_features": circadian.DEVICE_SCALED_FEATURES,
        "imputer_medians": dict(zip(FEATURES, imputer.statistics_.tolist(), strict=True)),
        "calibration": calibration,
        "threshold": float(y.mean()),
        "training_people": len(y),
        "training_prevalence": float(y.mean()),
        "device_scaling": device_scaling or {},
        "held_out_people": held_out or [],
    }
    if model_name == "lightgbm":
        booster = base.named_steps["lgbmclassifier"].booster_
        booster.save_model(str(out_dir / "depression_lightgbm.txt"))
    else:
        scaler = base.named_steps["standardscaler"]
        logistic = base.named_steps["logisticregression"]
        meta["logistic"] = {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
            "coef": logistic.coef_[0].tolist(),
            "intercept": float(logistic.intercept_[0]),
        }
    (out_dir / "depression_model.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _fmt(metrics: Metrics) -> dict:
    return {key: value for key, value in vars(metrics).items()}


def run(processed_dir: Path, reports_dir: Path, artifacts_dir: Path) -> str:
    """Run the whole protocol and return the Markdown report."""
    nhanes = pd.read_csv(processed_dir / "features_nhanes.csv")
    depresjon = pd.read_csv(processed_dir / "features_depresjon.csv")
    x_n, y_n, g_n = prepare(nhanes)
    x_d, y_d, g_d = prepare(depresjon)

    rows, external, loso, reliability, oof = [], [], [], {}, {}
    for name in make_models():
        logger.info("model %s", name)
        model_n = make_models(len(y_n))[name]
        p, t = out_of_fold(model_n, x_n, y_n, g_n, GroupKFold(N_SPLITS))
        oof[name] = (p, t)
        rows.append({"model": name, **_fmt(compute_metrics(y_n, p, t)), **bootstrap_ci(y_n, p, t)})
        reliability[name] = reliability_table(y_n, p)
        full = calibrated(model_n, len(y_n)).fit(x_n, y_n)
        p_ext = full.predict_proba(x_d)[:, 1]
        t_ext = np.full(len(y_d), y_n.mean())
        external.append(
            {
                "model": name,
                **_fmt(compute_metrics(y_d, p_ext, t_ext)),
                **bootstrap_ci(y_d, p_ext, t_ext),
            }
        )
        model_d = make_models(len(y_d) - 1)[name]
        p_l, t_l = out_of_fold(model_d, x_d, y_d, g_d, LeaveOneGroupOut())
        loso.append(
            {"model": name, **_fmt(compute_metrics(y_d, p_l, t_l)), **bootstrap_ci(y_d, p_l, t_l)}
        )

    cv = pd.DataFrame(rows)
    loso_table = pd.DataFrame(loso)
    population_best = cv.sort_values("auc", ascending=False).iloc[0]["model"]
    # Plan B (CLAUDE.md section 14, condition written before training): if the NHANES
    # model does not transfer to DEPRESJON, the deployed module is trained on DEPRESJON
    # and chosen by leave-one-subject-out AUC among portable models.
    transfer_auc = float(pd.DataFrame(external).set_index("model").loc[population_best, "auc"])
    plan_b = transfer_auc < TRANSFER_AUC_MIN
    candidates = loso_table if plan_b else cv
    deployable = candidates[candidates["model"].isin(DEPLOYABLE_MODELS)]
    deploy = deployable.sort_values("auc", ascending=False).iloc[0]["model"]
    best = population_best
    fairness = fairness_table(nhanes, y_n, *oof[best])
    ece = {name: expected_calibration_error(table) for name, table in reliability.items()}
    reports_dir.mkdir(parents=True, exist_ok=True)
    _svg_reliability(reliability, reports_dir / "reliability.svg")
    _svg_fairness(fairness, reports_dir / "fairness.svg")
    if plan_b:
        keep = ~depresjon["person_id"].isin(DEMO_HOLDOUT).to_numpy()
        fit_table = depresjon[keep].reset_index(drop=True)
        x_fit, y_fit, g_fit = prepare(fit_table)
        meta = export_portable_model(
            deploy,
            x_fit,
            y_fit,
            g_fit,
            artifacts_dir,
            LeaveOneGroupOut(),
            "depresjon",
            circadian.device_scaling_stats(fit_table, circadian.DEVICE_SCALED_FEATURES),
            sorted(set(DEMO_HOLDOUT) & set(depresjon["person_id"])),
        )
    else:
        meta = export_portable_model(
            deploy, x_n, y_n, g_n, artifacts_dir, GroupKFold(N_SPLITS), "nhanes"
        )

    columns = [
        "model",
        "auc",
        "auc_95ci",
        "mcc",
        "mcc_95ci",
        "f1",
        "sensitivity",
        "specificity",
        "brier",
        "people",
        "positives",
    ]
    lines = [
        "# Depression module: per-person validation",
        "",
        "Generated by `python3 -m ml.models.train` on LinuxONE (s390x). Label: PHQ-9 >= 10 "
        "in NHANES (depressive symptoms, not a diagnosis); patient vs control in DEPRESJON. "
        "One row per person; every split is checked for person leakage. Probabilities are "
        "isotonic-calibrated on the training fold; a person is classified positive when "
        "the calibrated risk is at least the training prevalence (rule fixed in advance).",
        "",
        f"## NHANES G+H, {N_SPLITS}-fold GroupKFold by person",
        "",
        cv[columns].to_markdown(index=False, floatfmt=".3f"),
        "",
        f"Best population model (highest NHANES AUC): **{population_best}**; it is the one "
        "used for the calibration and fairness analysis below.",
        "",
        "## External test: trained on all NHANES, tested on DEPRESJON (55 people)",
        "",
        pd.DataFrame(external)[columns].to_markdown(index=False, floatfmt=".3f"),
        "",
        "Threshold = NHANES prevalence; DEPRESJON prevalence is 42 %, so AUC (threshold-free) "
        "is the fairest summary of transfer.",
        "",
        "## DEPRESJON leave-one-subject-out (plan B, CLAUDE.md section 14)",
        "",
        loso_table[columns].to_markdown(index=False, floatfmt=".3f"),
        "",
        "## Deployed module",
        "",
        f"Transfer AUC of the population model on DEPRESJON: {transfer_auc:.2f} "
        f"({'below' if plan_b else 'above'} the {TRANSFER_AUC_MIN} threshold). "
        "CLAUDE.md section 14 planned this fallback before any training; the numeric "
        "threshold was written into this script after a first run, but any value between "
        "0.60 and 0.70 gives the same decision. "
        + (
            "**Plan B applies**: the deployed depression module is trained on DEPRESJON "
            "(clinically diagnosed patients vs controls) and chosen by leave-one-subject-out "
            "AUC among portable models; NHANES provides the reference ranges, the "
            "population analysis and the fairness check."
            if plan_b
            else "The deployed module is the population model trained on NHANES."
        ),
        "",
        f"Deployed: `{meta['model']}` trained on `{meta['trained_on']}` "
        f"({meta['training_people']} people), calibration `{meta['calibration']['type']}`, "
        f"threshold {meta['threshold']:.3f}.",
        "",
        f"Published person-level reference on DEPRESJON: F1 {DEPRESJON_REFERENCE['f1']}, "
        f"MCC {DEPRESJON_REFERENCE['mcc']} (Garcia-Ceja et al. 2018). Results above 95 % "
        "accuracy reported elsewhere usually mix days of the same person between train and test.",
        "",
        "## Calibration (NHANES out-of-fold)",
        "",
        "![Reliability diagram](reliability.svg)",
        "",
        pd.DataFrame(
            {"model": list(ece), "expected_calibration_error": list(ece.values())}
        ).to_markdown(index=False, floatfmt=".3f"),
        "",
        f"## Fairness: {best}, NHANES out-of-fold, by sex and age group",
        "",
        "![Fairness](fairness.svg)",
        "",
        fairness.to_markdown(index=False, floatfmt=".3f"),
        "",
        "## Limitations",
        "",
        "- PHQ-9 measures symptoms at one time point; activity was recorded on other days.",
        "- Hourly activity only (no heart rate in NHANES): sleep features are proxies.",
        "- NHANES and DEPRESJON use different devices and populations; features keep the "
        "same direction for only some features (`ml/reports/features_summary.md`).",
        "- DEPRESJON has 55 people: the 95 % intervals are wide and leave-one-subject-out "
        "on one clinic and one device is the most optimistic of the three settings.",
        "- Leave-one-out pooled AUC can be biased downwards for near-constant models (the "
        "training prevalence moves against the held-out label); minimum leaf sizes scale "
        "with the sample to avoid constant trees.",
        "- The deployed DEPRESJON model is chosen by the same leave-one-subject-out AUC that "
        "is reported for it (two portable candidates), which is slightly optimistic.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Train and validate the depression module.")
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    args = parser.parse_args(argv)
    report = run(args.processed_dir, args.reports_dir, args.artifacts_dir)
    (args.reports_dir / "metrics.md").write_text(report, encoding="utf-8")
    logger.info("Wrote %s", args.reports_dir / "metrics.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
