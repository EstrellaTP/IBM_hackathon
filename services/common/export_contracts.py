"""Export JSON Schemas and example payloads for the frontend and simulator.

Run from the repo root:  python -m services.common.export_contracts
Outputs to services/common/contracts/ (committed, regenerate after any schema change).
"""

import json
from datetime import timedelta
from pathlib import Path

from services.common import schemas as s

OUT = Path(__file__).parent / "contracts"
MODELS = [
    s.SignalBatch,
    s.EpisodeEvent,
    s.QuestionAnswer,
    s.ModuleRequest,
    s.ModuleResult,
    s.AuditEntry,
]


def examples() -> dict:
    """Build one valid example payload per contract, with realistic values."""
    t0 = s.utcnow().replace(microsecond=0)
    pid, eid = "p_7f3a2b", "e_9c1d4e"
    days = [(t0 - timedelta(days=11 - i)).date().isoformat() for i in range(12)]

    def ref(p10: float, p50: float, p90: float, group: str = "F_30-39") -> dict:
        return {"p10": p10, "p50": p50, "p90": p90, "group": group}

    return {
        "SignalBatch": s.SignalBatch(
            patient_id=pid,
            device="wesad",
            sent_at=t0,
            samples=[
                s.Sample(
                    t=t0 - timedelta(seconds=1),
                    hr=91.5,
                    acc_x=0.02,
                    acc_y=-0.01,
                    acc_z=0.99,
                    eda=0.41,
                ),
                s.Sample(t=t0, hr=92.0, acc_x=0.1, acc_y=0.0, acc_z=0.98, eda=0.42),
            ],
        ),
        "EpisodeEvent": s.EpisodeEvent(
            episode_id=eid,
            patient_id=pid,
            start=t0 - timedelta(seconds=60),
            detected_at=t0,
            score=3.4,
            method="zscore",
            features={"hr_z": 3.4, "acc_mag_z": 0.2, "eda_z": 2.1},
            timestamps=s.StageTimestamps(
                sample_t=t0,
                ingested_at=t0 + timedelta(milliseconds=110),
                inferred_at=t0 + timedelta(milliseconds=122),
                pushed_at=t0 + timedelta(milliseconds=125),
            ),
        ),
        "QuestionAnswer": s.QuestionAnswer(
            episode_id=eid,
            activity="work",
            mood_1_5=2,
            details=s.AnswerDetails(
                workload="demanding", emotion="anxious", something_happened=True
            ),
            answered_at=t0 + timedelta(seconds=20),
        ),
        "ModuleRequest": s.ModuleRequest(
            patient_id=pid,
            suspicion="depression",
            period=s.Period(**{"from": t0 - timedelta(days=12), "to": t0}),
        ),
        "ModuleResult": s.ModuleResult(
            patient_id=pid,
            suspicion="depression",
            result="compatible",
            confidence=0.78,
            model_version="dummy-0",
            data_quality={"valid_days": 12, "missing_hours": 6.5},
            episodes=[eid],
            metrics=[
                s.MetricEvidence(
                    name="daytime_activity",
                    unit="z (within-person)",
                    is_evidence=True,
                    shap=-0.21,
                    reference=ref(-1.0, 0.0, 1.0),
                    patient_series=[
                        {"day": d, "value": v}
                        for d, v in zip(
                            days,
                            [
                                -1.4,
                                -1.2,
                                -0.9,
                                -1.5,
                                -1.3,
                                -0.4,
                                -1.1,
                                -1.6,
                                -1.2,
                                -1.0,
                                -1.3,
                                -0.8,
                            ],
                            strict=True,
                        )
                    ],
                ),
                s.MetricEvidence(
                    name="sleep",
                    unit="awakenings/night",
                    is_evidence=True,
                    shap=-0.15,
                    reference=ref(1, 3, 6),
                    patient_series=[
                        {"day": d, "value": v}
                        for d, v in zip(days, [7, 8, 5, 9, 7, 4, 8, 9, 7, 6, 8, 7], strict=True)
                    ],
                ),
                s.MetricEvidence(
                    name="circadian_rhythm",
                    unit="IS (0-1)",
                    is_evidence=False,
                    shap=-0.04,
                    reference=ref(0.35, 0.55, 0.75),
                    patient_series=[
                        {"day": d, "value": v}
                        for d, v in zip(
                            days,
                            [0.5, 0.48, 0.52, 0.47, 0.5, 0.55, 0.49, 0.46, 0.5, 0.51, 0.48, 0.5],
                            strict=True,
                        )
                    ],
                ),
                s.MetricEvidence(name="heart_rate", unit="bpm (resting)", available=False),
            ],
        ),
    }


def main() -> None:
    """Write the JSON Schemas and example payloads to ``contracts/``."""
    OUT.mkdir(exist_ok=True)
    for m in MODELS:
        (OUT / f"{m.__name__}.schema.json").write_text(
            json.dumps(m.model_json_schema(by_alias=True), indent=2)
        )
    for name, obj in examples().items():
        (OUT / f"{name}.example.json").write_text(obj.model_dump_json(indent=2, by_alias=True))
    print(f"wrote {len(list(OUT.iterdir()))} files to {OUT}")


if __name__ == "__main__":
    main()
