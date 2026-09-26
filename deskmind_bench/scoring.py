"""Score finished runs from disk: the workspace, the run record and the trace. No driver, no desktop, no model.

A run directory, as DeskMind Hands writes it, holds:

    <runs_dir>/<run_id>/manifest.json   task id, fixture, harness commit
    <runs_dir>/<run_id>/run.json        final state, metrics, driver state, the grade the harness gave
    <runs_dir>/<run_id>/trace.jsonl     observations and steps
    <runs_dir>/<run_id>/ws/             the workspace as the run left it

Each run is graded again here with this package's graders against this checkout's task files, and summarised with
the same DONE-timing and latency fields as ``deskmind-bench run``. The harness's own grade is kept next to it
(``recorded_grade``) and disagreements are counted: a disagreement means the task files or graders differ from the
ones the run was made with, and the suite hash will say so too.

What cannot be regraded from disk: a check on the clipboard (``clipboard_equals``) -- the clipboard is not recorded.
The diag suite has none. Runs that never reached the model (environment, provider, harness failures) keep their
recorded grade; they are excluded from capability numbers either way.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .bench import SUITE_VERSION, aggregate, run_summary
from .failures import NOT_MODEL_FAULT
from .graders.primitives import GradeContext
from .graders.score import grade
from .suite import REPO, suite_hash
from .task import Task, load_set

#: Failure classes the harness derives from the grade itself; any other class was decided during the run and stands.
GRADE_DERIVED = {"none", "forbidden_side_effect", "false_completion", "planning"}
EXCLUDED = {c.value for c in NOT_MODEL_FAULT}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def pristine_sentinels(task: Task, fixtures_dir: Path) -> dict[str, str]:
    """Sentinel digests as the harness takes them: right after the fixture is unpacked, before the agent acts."""
    out = {}
    for s in task.sentinels:
        if not s.startswith("$WS/"):
            raise ValueError(f"{task.id}: sentinel {s!r} is not inside the workspace")
        out[s] = _sha256(fixtures_dir / (task.fixture or "") / s[len("$WS/"):])
    return out


def classify(state: str, g, recorded: dict | None) -> dict:
    """The run's failure class after regrading, by the harness's own rule (runtime loop, end of run)."""
    rec = recorded or {"class": "none", "detail": "", "auto": False}
    if g.error:
        return {"class": "harness_bug", "detail": f"grader error: {g.error}", "auto": True}
    if rec.get("class") not in GRADE_DERIVED:
        return rec
    if g.strict:
        return {"class": "none", "detail": "", "auto": False}
    if g.violations:
        return {"class": "forbidden_side_effect", "detail": "; ".join(g.violations), "auto": True}
    if state == "completed":
        return {"class": "false_completion", "detail": "agent declared done but checkpoints failed", "auto": True}
    if state == "cancelled":
        return {"class": "none", "detail": "cancelled by injection", "auto": False}
    return {"class": "planning", "detail": f"ended in state {state}", "auto": True}


def score_run(run_dir: Path, tasks: dict[str, Task], fixtures_dir: Path) -> dict:
    """One run, regraded. Returns the run record with ``grade`` and ``failure`` replaced."""
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    task = tasks.get(run["task_id"])
    if task is None:
        raise KeyError(f"{run_dir}: task {run['task_id']!r} is not in this suite")
    recorded_failure = run.get("failure") or {}
    ws = run_dir / "ws"
    out = {**run, "recorded_grade": run.get("grade"), "regraded": False}
    if recorded_failure.get("class") in EXCLUDED or not ws.is_dir():
        return out
    if any("clipboard_equals" in json.dumps(c.check) for c in task.checkpoints):
        out["regrade_note"] = "task checks the clipboard, which is not recorded; recorded grade kept"
        return out
    ctx = GradeContext(workspace=ws, vars=task.vars, clipboard=None,
                       driver_state=run.get("driver_state") or {},
                       run={"state": run.get("state"), "metrics": run.get("metrics") or {}})
    g = grade(task, ctx, sentinel_digests=pristine_sentinels(task, fixtures_dir))
    out.update(grade=g.to_json(), failure=classify(run.get("state"), g, recorded_failure), regraded=True)
    return out


def find_runs(paths: list[Path]) -> list[Path]:
    """Run directories from run directories, directories of runs, or DeskMind Hands report files."""
    found: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_file() and p.suffix == ".json":
            report = json.loads(p.read_text(encoding="utf-8"))
            base = Path(report["runs_dir"])
            found += [base / r["run_id"] for r in report.get("runs") or []]
        elif (p / "run.json").is_file():
            found.append(p)
        elif p.is_dir():
            found += sorted(d for d in p.iterdir() if (d / "run.json").is_file())
        else:
            raise FileNotFoundError(f"{p}: not a run directory, a directory of runs or a report")
    return found


def score(paths: list[Path], task_set: str = "diag", *, root: Path | None = None, label: str = "rescored",
          suite_version: str | None = None) -> dict:
    """Regrade and summarise. ``suite_version`` is the harness version the runs were made with, which a run
    directory does not record by name (its manifest has the harness commit); pass it to label the summary."""
    root = Path(root) if root else REPO
    tasks = {t.id: t for t in load_set(root / "tasks", task_set)}
    run_dirs = find_runs(paths)
    if not run_dirs:
        raise SystemExit("no runs found")
    scored = [score_run(d, tasks, root / "fixtures") for d in run_dirs]
    rows = [run_summary(r, d.parent) for r, d in zip(scored, run_dirs)]
    per_task: dict[str, list[dict]] = {}
    for r in rows:
        per_task.setdefault(r["task_id"], []).append(r)
    changed = [r["run_id"] for r in scored
               if r["regraded"] and bool((r.get("recorded_grade") or {}).get("strict")) != bool(r["grade"]["strict"])]
    commits = set()
    for d in run_dirs:
        try:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            commits.add((m.get("environment") or {}).get("harness_commit"))
        except (OSError, ValueError):
            pass
    return {
        "label": label, "task_set": task_set,
        "suite_version": suite_version, "suite_hash": suite_hash(task_set, root),
        "scorer_version": f"{task_set}-v{SUITE_VERSION}",
        "harness_commits": sorted(c for c in commits if c),
        "tasks": sorted(per_task),
        "aggregate": aggregate(rows),
        "per_task": {k: aggregate(v) for k, v in sorted(per_task.items())},
        "regrade": {"runs": len(scored), "regraded": sum(r["regraded"] for r in scored),
                    "strict_changed": changed},
        "runs": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
    }


def pass_table(summaries: list[dict]) -> str:
    """Markdown: passes per task (k/n) for each summary, the scored runs only."""
    tasks = sorted({t for s in summaries for t in s["per_task"]})
    head = "| task | " + " | ".join(s["label"] for s in summaries) + " |"
    lines = [head, "|---|" + "---|" * len(summaries)]
    for t in tasks:
        cells = []
        for s in summaries:
            a = s["per_task"].get(t)
            cells.append("" if a is None else f"{round(a['strict'] * a['scored'])}/{a['scored']}"
                         + (f" (+{a['unavailable']} env)" if a["unavailable"] else ""))
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    totals = []
    for s in summaries:
        a = s["aggregate"]
        totals.append(f"**{round(a['strict'] * a['scored'])}/{a['scored']}**"
                      + (f" (+{a['unavailable']} env)" if a["unavailable"] else ""))
    lines.append("| all | " + " | ".join(totals) + " |")
    return "\n".join(lines)
