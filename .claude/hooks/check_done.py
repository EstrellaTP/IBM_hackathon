"""Claude Code ``Stop`` hook that keeps the [CC] lane working until its work is done.

Claude Code runs this script every time the agent tries to end its turn. The script
collects the work still assigned to the [CC] lane (see CLAUDE.md §0.1) from three
sources:

1. Open GitHub issues labelled ``para-cc``.
2. Rows of ``docs/TASKS.md`` whose lane column mentions ``CC`` and whose status is
   pending (⬜) or in progress (🟡).
3. Unchecked ``- [ ] [CC]`` boxes in ``docs/QUALITY.md``.

If anything is pending, it prints ``{"decision": "block", "reason": ...}`` so Claude
Code feeds the list back to the agent instead of stopping. Escape valves (no time
limits by design):

* ``.claude/ALLOW_STOP`` exists (gitignored; a person creates it to release the agent).
* More than ``MAX_BLOCKS_WITHOUT_COMMIT`` consecutive blocks without any new commit,
  which signals the agent is stuck. The counter lives in ``.claude/.stop_count``
  (gitignored) and resets whenever ``HEAD`` changes.

Exit code is always 0: an exception would make Claude Code show a hook error, so
failures to read a source are reported inside the reason instead.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Stuck-agent safety valve required by task F0-CC-LOOP in docs/TASKS.md.
MAX_BLOCKS_WITHOUT_COMMIT = 60

# Statuses in docs/TASKS.md that still need work from the owning lane.
PENDING_STATUSES = ("⬜", "🟡")

# Seconds to wait for the GitHub CLI before giving up on the issues source.
GH_TIMEOUT_SECONDS = 20

ALLOW_STOP_FILE = Path(".claude") / "ALLOW_STOP"
STOP_COUNT_FILE = Path(".claude") / ".stop_count"
TASKS_FILE = Path("docs") / "TASKS.md"
QUALITY_FILE = Path("docs") / "QUALITY.md"

_LANE_CC = re.compile(r"\bCC\b")
_QUALITY_CC_OPEN = re.compile(r"^\s*-\s*\[ \]\s*\[CC\]\s*(?P<text>.+)$")
_BOLD_TITLE = re.compile(r"\*\*(?P<title>.+?)\*\*")


@dataclass
class PendingWork:
    """Work still assigned to the [CC] lane, grouped by source."""

    issues: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    quality: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True when no source reports pending work."""
        return not (self.issues or self.tasks or self.quality)


def project_root() -> Path:
    """Return the repository root (Claude Code sets ``CLAUDE_PROJECT_DIR``)."""
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def pending_tasks(tasks_markdown: str) -> list[str]:
    """Extract pending [CC] tasks from the ``docs/TASKS.md`` tables.

    A row counts when its lane column mentions ``CC`` (including shared lanes such as
    ``APP + CC``) and its status column is ⬜ or 🟡. Blocked tasks (⛔) are skipped on
    purpose: they wait on another lane, which is tracked through an issue.

    Args:
        tasks_markdown: Full text of ``docs/TASKS.md``.

    Returns:
        One ``"<ID> (<status>)"`` string per pending task, in file order.
    """
    pending: list[str] = []
    for line in tasks_markdown.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        # Task rows are: ID | description | lane | status [| dependencies].
        if len(cells) < 4 or not re.match(r"^F\d", cells[0]):
            continue
        task_id, lane, status = cells[0], cells[2], cells[3]
        if _LANE_CC.search(lane) and status.startswith(PENDING_STATUSES):
            pending.append(f"{task_id} ({status})")
    return pending


def pending_quality(quality_markdown: str) -> list[str]:
    """Extract unchecked ``- [ ] [CC]`` boxes from ``docs/QUALITY.md``.

    Args:
        quality_markdown: Full text of ``docs/QUALITY.md``.

    Returns:
        The bold title of each open box (or its full text if it has no bold title).
    """
    pending: list[str] = []
    for line in quality_markdown.splitlines():
        match = _QUALITY_CC_OPEN.match(line)
        if not match:
            continue
        text = match.group("text")
        title = _BOLD_TITLE.search(text)
        pending.append(title.group("title") if title else text.strip())
    return pending


def open_cc_issues(root: Path) -> list[str]:
    """List open GitHub issues labelled ``para-cc`` using the GitHub CLI.

    Args:
        root: Repository root, used as the working directory for ``gh``.

    Returns:
        One ``"#<number> <title>"`` string per open issue.

    Raises:
        RuntimeError: If ``gh`` is missing, times out or returns an error.
    """
    command = [
        "gh",
        "issue",
        "list",
        "--label",
        "para-cc",
        "--state",
        "open",
        "--json",
        "number,title",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"gh could not run: {error}") from error
    if result.returncode != 0:
        raise RuntimeError(f"gh failed: {result.stderr.strip()[:200]}")
    issues = json.loads(result.stdout or "[]")
    return [f"#{issue['number']} {issue['title']}" for issue in issues]


def _read_text(path: Path, work: PendingWork) -> str:
    """Read a coordination file, recording a warning instead of failing."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        work.warnings.append(f"could not read {path.name}: {error}")
        return ""


def collect_pending(root: Path) -> PendingWork:
    """Gather pending [CC] work from issues, TASKS.md and QUALITY.md.

    Args:
        root: Repository root.

    Returns:
        The pending work, with warnings for any source that could not be read.
    """
    work = PendingWork()
    try:
        work.issues = open_cc_issues(root)
    except (RuntimeError, json.JSONDecodeError) as error:
        work.warnings.append(f"issues not checked ({error})")
    work.tasks = pending_tasks(_read_text(root / TASKS_FILE, work))
    work.quality = pending_quality(_read_text(root / QUALITY_FILE, work))
    return work


def current_head(root: Path) -> str:
    """Return the current commit hash, or an empty string outside a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def register_block(root: Path) -> int:
    """Increment the consecutive-block counter, resetting it when HEAD has moved.

    Args:
        root: Repository root.

    Returns:
        The number of consecutive blocks without a new commit, including this one.
    """
    counter_path = root / STOP_COUNT_FILE
    head = current_head(root)
    state = {"head": head, "count": 0}
    try:
        stored = json.loads(counter_path.read_text(encoding="utf-8"))
        if stored.get("head") == head:
            state["count"] = int(stored.get("count", 0))
    except (OSError, ValueError, AttributeError):
        pass  # Missing or corrupt counter: start again from zero.
    state["count"] += 1
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    counter_path.write_text(json.dumps(state), encoding="utf-8")
    return state["count"]


def build_reason(work: PendingWork, block_count: int) -> str:
    """Compose the message Claude Code shows the agent when the stop is blocked."""
    lines = [
        "There is still [CC] work pending. Follow CLAUDE.md §0 and §0.1: "
        "para-cc issues (bloqueante first) -> CC tasks in docs/TASKS.md -> "
        "[CC] boxes in docs/QUALITY.md.",
    ]
    sections = (
        ("Open para-cc issues", work.issues),
        ("Pending CC tasks (TASKS.md)", work.tasks),
        ("Open [CC] boxes (QUALITY.md)", work.quality),
    )
    for title, items in sections:
        if items:
            lines.append(f"{title}: " + "; ".join(items))
    if work.warnings:
        lines.append("Warnings: " + "; ".join(work.warnings))
    lines.append(
        "If a task waits on another lane, mark it ⛔ and open an issue for that lane. "
        f"Block {block_count}/{MAX_BLOCKS_WITHOUT_COMMIT} without a new commit. "
        "A person can release you by creating .claude/ALLOW_STOP."
    )
    return "\n".join(lines)


def decide(root: Path) -> dict[str, str] | None:
    """Return the hook decision: a block payload, or None to allow the stop.

    Args:
        root: Repository root.

    Returns:
        ``{"decision": "block", "reason": ...}`` or ``None``.
    """
    if (root / ALLOW_STOP_FILE).exists():
        return None
    work = collect_pending(root)
    if work.is_empty():
        return None
    block_count = register_block(root)
    if block_count > MAX_BLOCKS_WITHOUT_COMMIT:
        return None
    return {"decision": "block", "reason": build_reason(work, block_count)}


def main() -> int:
    """Run the hook: read Claude Code's JSON from stdin and print the decision."""
    with contextlib.suppress(OSError, ValueError):
        sys.stdin.read()  # The payload is not needed; drain it so the pipe closes.
    decision = decide(project_root())
    if decision is not None:
        # ensure_ascii keeps the output safe on Windows consoles with legacy code pages.
        sys.stdout.write(json.dumps(decision))
    return 0


if __name__ == "__main__":
    sys.exit(main())
