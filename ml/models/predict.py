"""Load the portable depression model and score one person (used by suspicion-module).

The model written by :func:`ml.models.train.export_portable_model` is plain JSON
(logistic coefficients) or LightGBM text plus JSON, never a pickle, so it loads and
predicts identically on x86 laptops and on big-endian s390x (checked by
``ml/models/endianness_check.py``).

Contract for the suspicion module (issue #9)::

    model = load_model(path_to_artifacts)
    result = model.predict(features)   # features: {name: value} from ml.features.circadian
    result.probability                 # calibrated, 0-1
    result.compatible                  # probability >= model threshold
    result.contributions               # {feature: contribution to the log-odds}

Device-scaled features (L5, M10, daytime activity) must already be standardised within
the patient's reference population; :meth:`DepressionModel.standardise` does it with the
training statistics stored in the model.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ml.features.circadian import apply_device_scaling

MODEL_FILE = "depression_model.json"
LIGHTGBM_FILE = "depression_lightgbm.txt"


def sigmoid(value: float) -> float:
    """Numerically stable logistic function (no overflow for large |value|)."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


@dataclass(frozen=True)
class Prediction:
    """Score of one person."""

    probability: float
    compatible: bool
    raw_score: float
    contributions: dict[str, float]


class DepressionModel:
    """A calibrated classifier over the activity features.

    Args:
        meta: Content of ``depression_model.json``.
        booster: LightGBM booster when the model is a LightGBM one.
    """

    def __init__(self, meta: dict, booster=None) -> None:
        self.meta = meta
        self.features: list[str] = meta["features"]
        self.threshold: float = meta["threshold"]
        self._booster = booster

    @property
    def version(self) -> str:
        """Human-readable version for the audit log and the dashboard."""
        return f"{self.meta['model']}-{self.meta['trained_on']}-{self.meta['training_people']}"

    def _vector(self, features: dict[str, float]) -> np.ndarray:
        medians = self.meta["imputer_medians"]
        values = []
        for name in self.features:
            value = features.get(name)
            missing = value is None or (isinstance(value, float) and math.isnan(value))
            values.append(float(medians[name]) if missing else float(value))
        return np.asarray(values, dtype=np.float64)

    def _calibrate(self, raw_probability: float) -> float:
        calibration = self.meta["calibration"]
        if calibration["type"] == "isotonic":
            return float(np.interp(raw_probability, calibration["x"], calibration["y"]))
        clipped = min(max(raw_probability, 1e-6), 1 - 1e-6)
        logit = math.log(clipped / (1 - clipped))
        return sigmoid(calibration["a"] * logit + calibration["b"])

    def standardise(self, raw_features: dict[str, float]) -> dict[str, float]:
        """Scale device-scaled features with the training population's statistics."""
        return apply_device_scaling(raw_features, self.meta.get("device_scaling", {}))

    def predict_raw(self, raw_features: dict[str, float]) -> Prediction:
        """Score features straight from ``circadian.person_features`` (unscaled)."""
        return self.predict(self.standardise(raw_features))

    def predict(self, features: dict[str, float]) -> Prediction:
        """Score one person from their feature dictionary."""
        x = self._vector(features)
        if self.meta["model"] == "logistic":
            params = self.meta["logistic"]
            standardised = (x - np.asarray(params["mean"])) / np.asarray(params["scale"])
            terms = standardised * np.asarray(params["coef"])
            raw_score = float(terms.sum() + params["intercept"])
            contributions = dict(zip(self.features, terms.tolist(), strict=True))
        else:
            row = x.reshape(1, -1)
            raw_score = float(self._booster.predict(row, raw_score=True)[0])
            contrib = self._booster.predict(row, pred_contrib=True)[0][:-1]
            contributions = dict(zip(self.features, contrib.tolist(), strict=True))
        raw_probability = sigmoid(raw_score)
        probability = self._calibrate(raw_probability)
        return Prediction(
            probability=probability,
            compatible=probability >= self.threshold,
            raw_score=raw_score,
            contributions=contributions,
        )


def load_model(artifacts_dir: Path) -> DepressionModel:
    """Load the model from ``depression_model.json`` (and the LightGBM text if any)."""
    meta = json.loads((artifacts_dir / MODEL_FILE).read_text(encoding="utf-8"))
    booster = None
    if meta["model"] == "lightgbm":
        import lightgbm as lgb  # only needed for tree models

        booster = lgb.Booster(model_file=str(artifacts_dir / LIGHTGBM_FILE))
    return DepressionModel(meta, booster)
