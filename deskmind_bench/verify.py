"""Task self-verification without a driver: the effect oracle must pass, doing nothing must fail.

For every task: unpack the fixture into a temporary directory, run the task's ``oracle_effect`` shell commands there
(``mkdir``, ``mv``, ``printf`` and the like, confined to that directory), and grade. Outcome checkpoints must all
pass. Process checkpoints (how the task was done, e.g. "asked before acting") are skipped for the oracle -- it takes
no route -- and enforced for every real run. Then grade an untouched fixture as a run that declared DONE at once:
it must not pass, and must earn no partial credit unless the task says ``allow_vacuous``.

A task that fails either check is broken, not hard, and no score from it can be interpreted.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import dyn  # noqa: F401  -- registers the dynamic-task checks
from .graders.primitives import GradeContext
from .graders.score import grade
from .scoring import pristine_sentinels
from .suite import REPO
from .task import Task, load_set

NULL_METRICS = {"actions": 0, "dialogue_turns": 0, "stale_refusals": 0, "indeterminate_actions": 0,
                "parse_errors": 0, "failed_actions": 0}


def _unpack(task: Task, fixtures_dir: Path, into: Path) -> Path:
    ws = into / "ws"
    ws.mkdir()
    if task.fixture:
        for item in (fixtures_dir / task.fixture).iterdir():
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, ws / item.name)
    return ws


def _fixture(task: Task, fixtures_dir: Path) -> str | None:
    return str(fixtures_dir / task.fixture) if task.fixture else None


def verify_task(task: Task, fixtures_dir: Path) -> list[str]:
    problems: list[str] = []
    sentinels = pristine_sentinels(task, fixtures_dir)
    if task.oracle_effect:
        with tempfile.TemporaryDirectory(prefix="deskmind-bench-") as d:
            ws = _unpack(task, fixtures_dir, Path(d))
            env = {**os.environ, "WS": str(ws)}
            for cmd in task.oracle_effect:
                p = subprocess.run(["/bin/sh", "-c", cmd], cwd=ws, env=env, capture_output=True, text=True, timeout=60)
                if p.returncode != 0:
                    problems.append(f"effect step failed: {cmd[:60]!r} -> {(p.stderr or '').strip()[:120]}")
                    break
            else:
                g = grade(task, GradeContext(workspace=ws, vars=task.vars,
                                             run={"state": "completed", "metrics": {}, "dir": d,
                                                  "fixture_dir": _fixture(task, fixtures_dir)}),
                          sentinel_digests=sentinels)
                outcome = {c.name for c in task.checkpoints if not c.process}
                bad = [k for k, v in g.checkpoints.items() if not v.ok and k in outcome]
                if g.error or bad or g.violations:
                    problems.append(f"effect oracle does not reach the outcome: {g.error or ''} failed={bad} "
                                    f"{g.violations}")
    else:
        problems.append("no effect oracle")
    with tempfile.TemporaryDirectory(prefix="deskmind-bench-") as d:
        ws = _unpack(task, fixtures_dir, Path(d))
        g = grade(task, GradeContext(workspace=ws, vars=task.vars,
                                     run={"state": "completed", "metrics": dict(NULL_METRICS), "dir": d,
                                          "fixture_dir": _fixture(task, fixtures_dir)}),
                  sentinel_digests=sentinels)
        if g.strict:
            problems.append("doing nothing scores strict -- the grader is vacuous")
        if g.partial > 0 and not task.allow_vacuous:
            problems.append(f"doing nothing earns partial={g.partial:.2f} -- the fixture alone satisfies a checkpoint")
    return problems


def verify(task_set: str = "diag", root: Path | None = None, *, quiet: bool = False) -> int:
    root = Path(root) if root else REPO
    tasks = load_set(root / "tasks", task_set)
    bad = 0
    for t in tasks:
        problems = verify_task(t, root / "fixtures")
        bad += bool(problems)
        if not quiet:
            print(f"  [{'OK ' if not problems else 'BAD'}] {t.id}")
            for p in problems:
                print(f"        {p}")
    if not quiet:
        print(f"\n{len(tasks) - bad}/{len(tasks)} tasks verified in {task_set!r}")
    return 1 if bad else 0
