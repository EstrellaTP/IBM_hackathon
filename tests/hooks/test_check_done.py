import importlib.util
import json
import sys
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "check_done.py"
_spec = importlib.util.spec_from_file_location("check_done", HOOK_PATH)
check_done = importlib.util.module_from_spec(_spec)
# dataclasses resolve annotations through sys.modules, so register before executing.
sys.modules["check_done"] = check_done
_spec.loader.exec_module(check_done)

TASKS_SAMPLE = """
| ID | Tarea | Carril | Estado | Depende de |
|---|---|---|---|---|
| F0-BE-01 | Verify VM | CC | ⬜ | — |
| F0-BE-02 | Install libs | CC | 🟡 | F0-BE-01 |
| F0-BE-03 | Compose | APP | ⬜ | — |
| F0-BE-04 | Deploy | CC | ⛔ | F0-BE-03 |
| F0-CC-LOOP | Hook | CC | ✅ | — |
| F3-ML-03 | Detector v2 | APP (código) + CC (ejecución) | ⬜ | F1-ML-01 |
| F4-ML-01 | Final script | APP + CC | ⬜ |
| F5-01 | Wearable | CC + HUM | ✅ |
"""

QUALITY_SAMPLE = """
- [ ] [CC] **Corte vertical en la VM**: details. (R3)
- [x] [CC] **Done already**: details.
- [ ] [APP] **Not ours**: details.
- [~] [CC] **Impossible**: details.
- [ ] [CC] plain text without bold
"""


def _make_repo(tmp_path: Path, tasks: str, quality: str) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "TASKS.md").write_text(tasks, encoding="utf-8")
    (tmp_path / "docs" / "QUALITY.md").write_text(quality, encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    return tmp_path


@pytest.fixture
def no_issues(monkeypatch):
    monkeypatch.setattr(check_done, "open_cc_issues", lambda root: [])


def test_pending_tasks_keeps_only_cc_rows_in_pending_or_in_progress():
    assert check_done.pending_tasks(TASKS_SAMPLE) == [
        "F0-BE-01 (⬜)",
        "F0-BE-02 (🟡)",
        "F3-ML-03 (⬜)",
        "F4-ML-01 (⬜)",
    ]


def test_pending_quality_returns_bold_titles_of_open_cc_boxes_only():
    assert check_done.pending_quality(QUALITY_SAMPLE) == [
        "Corte vertical en la VM",
        "plain text without bold",
    ]


def test_decide_blocks_and_lists_pending_work(tmp_path, no_issues):
    root = _make_repo(tmp_path, TASKS_SAMPLE, QUALITY_SAMPLE)
    decision = check_done.decide(root)
    assert decision["decision"] == "block"
    assert "F0-BE-01" in decision["reason"]
    assert "Corte vertical en la VM" in decision["reason"]
    assert "CLAUDE.md §0" in decision["reason"]


def test_decide_allows_stop_when_allow_stop_file_exists(tmp_path, no_issues):
    root = _make_repo(tmp_path, TASKS_SAMPLE, QUALITY_SAMPLE)
    (root / ".claude" / "ALLOW_STOP").touch()
    assert check_done.decide(root) is None


def test_decide_allows_stop_when_nothing_is_pending(tmp_path, no_issues):
    root = _make_repo(tmp_path, "| F0-X | done | CC | ✅ | — |", "- [x] [CC] **Done**")
    assert check_done.decide(root) is None


def test_decide_blocks_on_open_issue_even_without_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(check_done, "open_cc_issues", lambda root: ["#7 Fix it"])
    root = _make_repo(tmp_path, "", "")
    assert "#7 Fix it" in check_done.decide(root)["reason"]


def test_decide_releases_after_too_many_blocks_without_commit(tmp_path, no_issues):
    root = _make_repo(tmp_path, TASKS_SAMPLE, QUALITY_SAMPLE)
    for _ in range(check_done.MAX_BLOCKS_WITHOUT_COMMIT):
        assert check_done.decide(root) is not None
    assert check_done.decide(root) is None


def test_block_counter_resets_when_head_changes(tmp_path, monkeypatch):
    root = _make_repo(tmp_path, "", "")
    monkeypatch.setattr(check_done, "current_head", lambda root: "aaa")
    check_done.register_block(root)
    assert check_done.register_block(root) == 2
    monkeypatch.setattr(check_done, "current_head", lambda root: "bbb")
    assert check_done.register_block(root) == 1
    stored = json.loads((root / ".claude" / ".stop_count").read_text(encoding="utf-8"))
    assert stored == {"head": "bbb", "count": 1}


def test_decide_reports_issue_source_failure_as_warning(tmp_path, monkeypatch):
    def failing(root):
        raise RuntimeError("gh failed: offline")

    monkeypatch.setattr(check_done, "open_cc_issues", failing)
    root = _make_repo(tmp_path, TASKS_SAMPLE, "")
    assert "issues not checked" in check_done.decide(root)["reason"]
