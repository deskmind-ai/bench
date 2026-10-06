"""Tier O's bench runner side: fires a dyn task's changes at the orchestrator's hook points (#62).

The runner reads the task (its changes, its reference plan, its checkpoints); the orchestrator never does. Triggers:

- at_start: before the plan is written;
- before_subgoal: <reference part id>: when the orchestrator first starts its k-th part, k being that id's position
  in the task's reference_plan (the orchestrator's own ids differ; parts are matched by order);
- on_ask: {kind?: clarify | plan_confirm}: the first time the orchestrator asks the user (that kind);
- at_checkpoint: <name> / at_state: <check>: after each part, once the check passes.

at_action needs the per-step loop and is left to hands (hands#22) when it runs a task itself. What a change makes the
user say is appended to <run_dir>/user_queue.jsonl, where the orchestrator's user reads interjections.

Matching by position fails quietly when the orchestrator splits the goal differently from reference_plan, so every
part started is written to <run_dir>/hooks.jsonl with the reference id it was matched to: the T7 analysis reads it
to find runs where a before_subgoal change landed on a different part than intended.
"""
from __future__ import annotations

import json
from pathlib import Path

from ...graders.primitives import GradeContext, evaluate
from ..inject import Injector


class ChangeHooks:
    def __init__(self, task, ws: Path, run_dir: Path, run_id: str, injector: Injector | None = None,
                 fixture_dir: Path | None = None) -> None:
        self.task, self.ws, self.run_dir = task, Path(ws), Path(run_dir)
        # The pristine fixture, for at_state checks that tell what the run changed (unconfirmed_writes and the like).
        self.run_info = {"dir": str(self.run_dir), "fixture_dir": str(fixture_dir) if fixture_dir else None}
        self.injector = injector or Injector(ws, run_dir, run_id, apps=tuple({task.app, *task.reset_apps}))
        self.order = [p.get("id") for p in task.reference_plan]
        self.by_name = {c.name: c for c in task.checkpoints}

    def _fire(self, change) -> None:
        said = self.injector.fire(change)
        if said:
            with (self.run_dir / "user_queue.jsonl").open("a", encoding="utf-8") as f:
                for text in said:
                    f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")

    def _pending(self, key: str):
        return [c for c in self.task.changes if key in c.trigger and c.id not in self.injector.fired]

    def at_start(self) -> None:
        for c in self._pending("at_start"):
            self._fire(c)

    def before_subgoal(self, k: int, clause: str) -> None:
        ref = self.order[k - 1] if 0 < k <= len(self.order) else None
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "hooks.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"k": k, "clause": clause, "reference": ref}, ensure_ascii=False) + "\n")
        for c in self._pending("before_subgoal"):
            if c.trigger["before_subgoal"] == ref:
                self._fire(c)

    def after_subgoal(self) -> None:
        ctx = GradeContext(workspace=self.ws, vars=self.task.vars, run=self.run_info)
        for c in self._pending("at_checkpoint") + self._pending("at_state"):
            if "at_checkpoint" in c.trigger:
                cp = self.by_name.get(c.trigger["at_checkpoint"])
                if cp is None:
                    raise ValueError(f"change {c.id}: no checkpoint named {c.trigger['at_checkpoint']!r}")
                due = evaluate(cp.check, ctx).ok
            else:
                due = evaluate(c.trigger["at_state"], ctx).ok
            if due:
                self._fire(c)

    def on_ask(self, kind: str, text: str) -> None:
        for c in self._pending("on_ask"):
            want = (c.trigger.get("on_ask") or {}).get("kind") if isinstance(c.trigger.get("on_ask"), dict) else None
            if want in (None, kind):
                self._fire(c)

    def close(self) -> None:
        self.injector.close()
