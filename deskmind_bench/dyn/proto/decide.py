"""Decision points (#60): what to do after a subgoal. Code decides when nothing is wrong; otherwise a model answers a
multiple-choice question over options the code offers, in a fixed order."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from .events import CHOICES

_DESCRIBE = {
    "continue": "Go on to the next part of the plan as it is.",
    "repair": "Do this part again, adjusted for what went wrong; the plan stays the same.",
    "replan": "The rest of the plan no longer fits: write the remaining parts again.",
    "ask": "Ask the user: information is missing, or the change touches something they confirmed.",
    "handoff": "Hand this over to the stronger cloud model.",
    "stop": "Stop and report what is done and why the rest cannot be.",
}


@dataclass
class Context:
    goal: str
    plan_version: int
    parts: list[dict]            # [{"id", "goal", "status": "done" | "now" | "todo"}]
    outcome: str
    detail: str
    signals: list[str]
    can_repair: bool
    can_replan: bool
    can_ask: bool
    can_handoff: bool

    def options(self) -> list[str]:
        allowed = {"continue", "stop"} | ({"repair"} if self.can_repair else set()) | \
                  ({"replan"} if self.can_replan else set()) | ({"ask"} if self.can_ask else set()) | \
                  ({"handoff"} if self.can_handoff else set())
        return [c for c in CHOICES if c in allowed]


def by_code(ctx: Context) -> str | None:
    """Nothing to decide: the part was met and no signal fired. No model call (survey: decide every subgoal, but
    only spend a model on it when something is off)."""
    return "continue" if ctx.outcome == "met" and not ctx.signals else None


class SystemOneDecider:
    """The local Brain answers the decision as one choice question over /v1/systemone. This question is new to the
    model (never trained); T7 measures whether it can answer it at all."""

    def __init__(self, url: str = "http://127.0.0.1:8793", token: str | None = None, timeout: float = 60.0) -> None:
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def decide(self, ctx: Context) -> tuple[str, dict | None, str]:
        opts = ctx.options()
        body = {
            "state": {"goal": ctx.goal, "plan": ctx.parts, "last_part": {"outcome": ctx.outcome, "detail": ctx.detail[:400]},
                      "signals": ctx.signals},
            "questions": {"next": {"type": "choice",
                                   "instructions": {"goal": ctx.goal, "rules": [
                                       "Decide what the agent does next, given the plan and what just happened.",
                                       "Signals were detected by code and are reliable. Do not continue past a "
                                       "signal that makes the next part impossible."]},
                                   "criteria": {o: _DESCRIBE[o] for o in opts}}},
        }
        req = urllib.request.Request(self.url + "/v1/systemone", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            reply = json.load(r)
        ans = reply["answers"]["next"]
        probs = ans.get("probabilities") or {}
        choice = max(opts, key=lambda o: probs.get(o, 0.0))       # ties: first in the offered order
        tier = (reply.get("routing") or {}).get("by")
        by = {"fast": "local-0.8b", "strong": "local-4b"}.get(tier, "local-4b")
        return choice, {o: round(float(probs.get(o, 0.0)), 4) for o in opts}, by


class ScriptedDecider:
    """For tests and for the fixed arms: a function from the context to a choice."""

    def __init__(self, fn, by: str = "local-4b") -> None:
        self.fn, self.by = fn, by

    def decide(self, ctx: Context) -> tuple[str, dict | None, str]:
        choice = self.fn(ctx)
        assert choice in ctx.options(), (choice, ctx.options())
        return choice, None, self.by
