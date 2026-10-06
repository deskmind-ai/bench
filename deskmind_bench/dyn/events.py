"""The typed events a dynamic-task run leaves behind, version 1 (deskmind#62, deskmind#60's interface with #58).

Two files in a run directory, one JSON object per line:

    orchestrator.jsonl   written by the orchestrator: plans, decisions, subgoals, questions, the end
    changes.jsonl        written by the bench runner: which change fired when. The orchestrator never reads it, and
                         nothing in it reaches the model -- grader output that leaks into the agent's context is a
                         known way benchmarks go wrong (BrowserGym posted validator progress as a user message).

Writes are not events here: they happen inside the harness and are read from its own trace and from the workspace
(see graders.py). Step approvals likewise stay in the harness trace.

Behaviour is graded from these events only, never from free text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VERSION = 1

CHOICES = ("continue", "repair", "replan", "ask", "handoff", "stop")
DECIDERS = ("local-0.8b", "local-4b", "cloud", "template")
CHANNELS = ("gui", "oplist", "app")
OUTCOMES = ("met", "unmet", "needs_user", "handoff", "failed")
ASK_KINDS = ("clarify", "plan_confirm", "step_approval")
USER_KINDS = ("reply", "interject")
END_STATES = ("completed", "stopped", "failed", "handoff")
WRITE_CLASSES = ("write", "terminal")
#: What can prompt a decision. A closed set in v1, so graders and reports can count them.
SIGNALS = ("post_mismatch", "new_window", "file_missing", "app_absent", "guard_fired", "user_interjected",
           "budget_half", "write_conflict")

_STR, _INT, _BOOL, _FLOAT = "str", "int", "bool", "float"


def _enum(*values: str) -> tuple:
    return ("enum", values)


def _list(item) -> tuple:
    return ("list", item)


def _opt(spec) -> tuple:
    return ("opt", spec)


_SUBGOAL = {"id": _STR, "goal": _STR, "post": _opt(_STR), "channel": _enum(*CHANNELS)}
_WRITE = {"class": _enum(*WRITE_CLASSES), "op": _STR, "src": _opt(_STR), "dst": _opt(_STR)}

#: Field name -> type, per event, beside the fields every event carries (t, v, ts, run).
FIELDS: dict[str, dict[str, Any]] = {
    "plan_proposed": {"version": _INT, "by": _enum(*DECIDERS), "subgoals": _list(_SUBGOAL), "writes": _list(_WRITE)},
    "plan_confirmed": {"version": _INT, "approved": _BOOL, "reply": _STR},
    "subgoal_start": {"id": _STR, "plan_version": _INT, "channel": _enum(*CHANNELS),
                      "budget": {"max_actions": _INT}},
    "subgoal_end": {"id": _STR, "plan_version": _INT, "outcome": _enum(*OUTCOMES), "signals": _list(_enum(*SIGNALS)),
                    "steps": _INT, "hands_run": _opt(_STR), "model_calls": {"local": _INT, "cloud": _INT}},
    "decision": {"dp": _INT, "choice": _enum(*CHOICES), "plan_version": _INT, "signals": _list(_enum(*SIGNALS)),
                 "by": _enum(*DECIDERS), "options": _list(_STR), "probabilities": _opt(("map", _FLOAT))},
    "ask": {"kind": _enum(*ASK_KINDS), "text": _STR, "options": _list(_STR)},
    "user_msg": {"kind": _enum(*USER_KINDS), "text": _STR, "slot": _opt(_STR)},
    "done": {"state": _enum(*END_STATES), "report": _STR},
    # changes.jsonl
    "change_fired": {"change_id": _STR, "type": _STR, "effect": _opt(("any",))},
    #: How a change that waits for an answer ended, written at teardown: the button clicked on an injected dialog
    #: (macOSWorld's in_process outcome), or not_handled when it was still open.
    "change_outcome": {"change_id": _STR, "outcome": _enum("gold", "distract", "not_handled", "other"),
                       "button": _opt(_STR)},
}
CHANGE_EVENTS = ("change_fired", "change_outcome")
ORCHESTRATOR_EVENTS = tuple(k for k in FIELDS if k not in CHANGE_EVENTS)


def _check(value: Any, spec: Any, where: str) -> list[str]:
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            return [f"{where}: expected an object"]
        out = [f"{where}.{k}: missing" for k in spec if k not in value and not _optional(spec[k])]
        for k, s in spec.items():
            if k in value:
                out += _check(value[k], s, f"{where}.{k}")
        return out
    if spec == _STR:
        return [] if isinstance(value, str) else [f"{where}: expected a string"]
    if spec == _INT:
        return [] if isinstance(value, int) and not isinstance(value, bool) else [f"{where}: expected an integer"]
    if spec == _BOOL:
        return [] if isinstance(value, bool) else [f"{where}: expected true or false"]
    if spec == _FLOAT:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return [] if ok else [f"{where}: expected a number"]
    kind = spec[0]
    if kind == "enum":
        return [] if value in spec[1] else [f"{where}: {value!r} is not one of {', '.join(spec[1])}"]
    if kind == "list":
        if not isinstance(value, list):
            return [f"{where}: expected a list"]
        return [e for i, v in enumerate(value) for e in _check(v, spec[1], f"{where}[{i}]")]
    if kind == "opt":
        return [] if value is None else _check(value, spec[1], where)
    if kind == "map":
        if not isinstance(value, dict):
            return [f"{where}: expected an object"]
        return [e for k, v in value.items() for e in _check(v, spec[1], f"{where}[{k!r}]")]
    if kind == "any":
        return []
    raise ValueError(f"bad spec {spec!r}")


def _optional(spec: Any) -> bool:
    return isinstance(spec, tuple) and spec[0] == "opt"


def validate(event: Any) -> list[str]:
    """What is wrong with one event, or [] when it conforms to version 1."""
    if not isinstance(event, dict):
        return ["an event is a JSON object"]
    t = event.get("t")
    if t not in FIELDS:
        return [f"unknown event {t!r}"]
    out = []
    if event.get("v") != VERSION:
        out.append(f"{t}: v is {event.get('v')!r}, not {VERSION}")
    out += _check(event.get("ts"), _FLOAT, f"{t}.ts")
    out += _check(event.get("run"), _STR, f"{t}.run")
    out += _check({k: v for k, v in event.items() if k not in ("t", "v", "ts", "run")}, FIELDS[t], t)
    return out


def read(path: Path) -> list[dict]:
    """The events of one file, in order; [] when there is no file. A line that does not conform is an error: a run
    whose record cannot be read cannot be graded, and grading it as "no decision" would hide the bug."""
    if not path.exists():
        return []
    events = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        e = json.loads(line)
        bad = validate(e)
        if bad:
            raise ValueError(f"{path.name}:{n}: {'; '.join(bad)}")
        events.append(e)
    return events


def run_events(run_dir: Path) -> tuple[list[dict], list[dict]]:
    """(orchestrator events, change events) of a run directory, each in time order."""
    orch = read(Path(run_dir) / "orchestrator.jsonl")
    changes = read(Path(run_dir) / "changes.jsonl")
    for e in orch:
        if e["t"] in CHANGE_EVENTS:
            raise ValueError(f"{e['t']} belongs in changes.jsonl, which the orchestrator never writes")
    for e in changes:
        if e["t"] not in CHANGE_EVENTS:
            raise ValueError(f"changes.jsonl holds only {' and '.join(CHANGE_EVENTS)}, not {e['t']!r}")
    return sorted(orch, key=lambda e: e["ts"]), sorted(changes, key=lambda e: e["ts"])
