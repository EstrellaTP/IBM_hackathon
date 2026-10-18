import json
from datetime import datetime, timezone

import pandas as pd

from services.common.schemas import SignalBatch
from tools.benchmark import run_benchmark as bench


def test_batch_body_is_a_valid_signal_batch_at_the_benchmark_rate():
    template = bench.batch_template()
    body = bench.build_body("p_00aa11bb", template, datetime(2026, 1, 1, tzinfo=timezone.utc))
    batch = SignalBatch.model_validate(json.loads(body))
    acc = [s for s in batch.samples if s.acc_x is not None]
    hr = [s for s in batch.samples if s.hr is not None]
    assert len(acc) == bench.BATCH_SECONDS * bench.ACC_HZ_FOR_BENCHMARK
    assert len(hr) == bench.BATCH_SECONDS


def test_summary_reports_percentiles_and_errors_per_level(tmp_path):
    rows = [
        bench.RequestResult(10, "p_1", float(i), 202, 100.0 + i, 5.0 + i, 0.5, 0)
        for i in range(100)
    ] + [bench.RequestResult(10, "p_1", 100.0, 0, 30000.0, None, None, 0)]
    summary = bench.summarise(pd.DataFrame([vars(r) for r in rows]))
    [level] = summary.to_dict("records")
    assert level["errors"] == 1 and level["requests"] == 101
    assert level["server_ms_p50"] == 54.5
    bench.svg_chart(summary, tmp_path / "chart.svg")
    assert (tmp_path / "chart.svg").read_text().startswith("<svg")
