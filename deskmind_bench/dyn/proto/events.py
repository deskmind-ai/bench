"""Writing orchestrator.jsonl. The schema is deskmind_bench.dyn.events (version 1, #62); every line is validated
against it before it is written, so a run that would not grade fails at once, not in the grader."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import events as schema

CHOICES = schema.CHOICES


class EventLog:
    def __init__(self, path: Path, run: str) -> None:
        self.path, self.run = Path(path), run
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.dp = 0

    def _emit(self, t: str, **fields) -> dict:
        ev = {"t": t, "v": schema.VERSION, "ts": round(time.time(), 3), "run": self.run, **fields}
        errors = schema.validate(ev)
        if errors:
            raise ValueError(f"{t}: {'; '.join(errors)}")
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def plan_proposed(self, version: int, by: str, subgoals: list[dict], writes: list[dict]) -> dict:
        return self._emit("plan_proposed", version=version, by=by, subgoals=subgoals, writes=writes)

    def plan_confirmed(self, version: int, approved: bool, reply: str) -> dict:
        return self._emit("plan_confirmed", version=version, approved=approved, reply=reply)

    def subgoal_start(self, id: str, plan_version: int, channel: str, max_actions: int) -> dict:
        return self._emit("subgoal_start", id=id, plan_version=plan_version, channel=channel,
                          budget={"max_actions": max_actions})

    def subgoal_end(self, id: str, plan_version: int, outcome: str, signals: list[str], steps: int,
                    hands_run: str | None, model_calls: dict) -> dict:
        return self._emit("subgoal_end", id=id, plan_version=plan_version, outcome=outcome, signals=signals,
                          steps=steps, hands_run=hands_run, model_calls=model_calls)

    def decision(self, choice: str, plan_version: int, signals: list[str], by: str, options: list[str],
                 probabilities: dict | None) -> dict:
        if choice not in options:
            raise ValueError(f"decision {choice!r} was not among the options {options}")
        self.dp += 1
        return self._emit("decision", dp=self.dp, choice=choice, plan_version=plan_version, signals=signals, by=by,
                          options=options, probabilities=probabilities)

    def ask(self, kind: str, text: str, options: list[str]) -> dict:
        return self._emit("ask", kind=kind, text=text, options=options)

    def user_msg(self, kind: str, text: str, slot: str | None) -> dict:
        return self._emit("user_msg", kind=kind, text=text, slot=slot)

    def done(self, state: str, report: str) -> dict:
        return self._emit("done", state=state, report=report)


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
