"""Executors run one subgoal and report its outcome. The orchestrator never looks inside a run."""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .plan import Subgoal

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_END = re.compile(r"^(completed|errored|budget_exhausted|stopped|failed|cancelled|blocked)\s+(\d+) actions", re.M)


@dataclass
class Result:
    outcome: str                   # met | unmet | needs_user | handoff | failed
    steps: int = 0
    detail: str = ""
    hands_run: str | None = None   # the per-step agent's trace directory, if it has one
    model_calls: dict = field(default_factory=lambda: {"local": 0, "cloud": 0})


class HandsDoExecutor:
    """Runs a subgoal as `deskmind-hands do` on the real desktop (#62 Tier D), with the local Brain as the planner.

    The agent's own questions and step approvals come out as HANDS_ASK lines; they go to the orchestrator's user and
    are journalled as `ask` / `user_msg` (kind step_approval or clarify). Writes happen inside hands; the grader
    reads them from its trace and the disk diff (#62)."""

    def __init__(self, hands_project: Path, systemone_url: str, run_dir: Path, app: str = "com.apple.finder",
                 apps: str = "", extra: list[str] | None = None) -> None:
        self.hands_project, self.url, self.app, self.apps = Path(hands_project), systemone_url, app, apps
        self.run_dir = Path(run_dir)
        self.extra = extra or []

    def run(self, sg: Subgoal, ws: Path, max_actions: int, user, log, constraints: str = "") -> Result:
        goal = sg.goal + (f"。{constraints}" if constraints else "")
        cmd = ["uv", "run", "--quiet", "--project", str(self.hands_project), "deskmind-hands", "do", goal,
               "--in", str(ws), "--adapter", "systemone", "--systemone-url", self.url, "--app", self.app,
               "--max-actions", str(max_actions), "--ask", "stdin", "--yes", "--no-screenshots", *self.extra]
        if self.apps:
            cmd += ["--apps", self.apps]
        # hands writes its run under <run_dir>/hands, and prints the trace path relative to <run_dir>: the grader
        # joins run_dir / hands_run (#62, graders.hands_traces).
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             env={**os.environ, "NO_COLOR": "1", "DESKMIND_RUNS_DIR": str(self.run_dir / "hands")})
        out = []
        for line in p.stdout:
            line = _ANSI.sub("", line)
            out.append(line)
            if line.startswith("HANDS_ASK "):
                q = json.loads(line[len("HANDS_ASK "):])
                kind = "step_approval" if q.get("approval") else "clarify"
                log.ask(kind, q["question"], list(q.get("options") or []))
                reply, ok, slot = user.respond(q["question"], approval=bool(q.get("approval")))
                log.user_msg("reply", reply, slot)
                p.stdin.write(json.dumps({"reply": reply, "approve": ok}, ensure_ascii=False) + "\n")
                p.stdin.flush()
        p.wait()
        text = "".join(out)
        m = _END.search(text)
        state, steps = (m.group(1), int(m.group(2))) if m else ("failed", 0)
        trace = re.search(r"^trace (\S+)", text, re.M)
        outcome = {"completed": "met"}.get(state, "unmet" if state in ("budget_exhausted", "blocked") else "failed")
        return Result(outcome, steps, detail=text[-600:], hands_run=trace.group(1) if trace else None,
                      model_calls={"local": steps, "cloud": 0})


class FnExecutor:
    """Runs a subgoal with a Python function (tests, and Tier O tasks whose parts are file operations)."""

    def __init__(self, fn) -> None:
        self.fn = fn

    def run(self, sg: Subgoal, ws: Path, max_actions: int, user, log, constraints: str = "") -> Result:
        return self.fn(sg, ws, max_actions)
