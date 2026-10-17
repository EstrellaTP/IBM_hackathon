from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from services.common.schemas import (
    EpisodeEvent, MetricEvidence, ModuleRequest, ModuleResult, QuestionAnswer,
    ReferenceRange, Sample, SignalBatch, StageTimestamps, new_episode_id, new_patient_id,
)

T0 = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
PID = "p_7f3a"


def test_signal_batch_roundtrip():
    b = SignalBatch(patient_id=PID, device="wesad", sent_at=T0,
                    samples=[Sample(t=T0, hr=92, acc_x=0.1, acc_y=0, acc_z=0.98, eda=0.42)])
    assert SignalBatch.model_validate_json(b.model_dump_json()) == b


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        Sample(t=datetime(2026, 10, 17, 12, 0), hr=80)


def test_unsorted_samples_rejected():
    with pytest.raises(ValidationError):
        SignalBatch(patient_id=PID, device="sim", sent_at=T0,
                    samples=[Sample(t=T0 + timedelta(seconds=1)), Sample(t=T0)])


def test_bad_patient_id_rejected():
    with pytest.raises(ValidationError):
        SignalBatch(patient_id="maria.garcia", device="sim", sent_at=T0, samples=[Sample(t=T0)])


def test_episode_server_latency():
    ts = StageTimestamps(sample_t=T0, ingested_at=T0, inferred_at=T0 + timedelta(milliseconds=12))
    ev = EpisodeEvent(patient_id=PID, start=T0, detected_at=T0, score=3.4, method="zscore", timestamps=ts)
    assert ev.episode_id.startswith("e_")
    assert ts.server_latency_ms() == pytest.approx(12)


def test_empty_answer_rejected():
    with pytest.raises(ValidationError):
        QuestionAnswer(episode_id=new_episode_id(), answered_at=T0)


def test_mood_range():
    with pytest.raises(ValidationError):
        QuestionAnswer(episode_id=new_episode_id(), mood_1_5=7, answered_at=T0)


def test_module_request_uses_from_alias():
    r = ModuleRequest.model_validate({"patient_id": PID, "suspicion": "depression",
                                      "period": {"from": T0.isoformat(), "to": (T0 + timedelta(days=12)).isoformat()}})
    assert '"from"' in r.model_dump_json(by_alias=True)


def test_module_result_limits():
    metric = lambda n: MetricEvidence(name=n, reference=ReferenceRange(p10=1, p50=2, p90=3, group="F_30-39"))
    ok = ModuleResult(patient_id=new_patient_id(), suspicion="depression", result="compatible",
                      confidence=0.78, model_version="dummy-0",
                      data_quality={"valid_days": 12, "missing_hours": 6.5},
                      metrics=[metric(n) for n in ["sleep", "circadian_rhythm", "daytime_activity", "heart_rate"]])
    assert len(ok.metrics) == 4
    with pytest.raises(ValidationError):
        ModuleResult(**{**ok.model_dump(), "metrics": [metric("sleep"), metric("sleep")]})
    with pytest.raises(ValidationError):
        ReferenceRange(p10=3, p50=2, p90=1, group="M_20-29")


def test_examples_validate():
    from services.common.export_contracts import examples
    for name, obj in examples().items():
        type(obj).model_validate_json(obj.model_dump_json(by_alias=True))
