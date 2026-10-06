"""Declarative task schema.

A task is data, not code. The cost of authoring one is the ceiling on how many
you will ever have, and the number of tasks is the resolution of every decision
you make afterwards. Anything a task needs that is not expressible here is a
missing grader primitive or a missing injection type -- add it there, once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class TaskError(ValueError):
    pass


@dataclass
class Checkpoint:
    name: str
    check: dict
    weight: float = 1.0
    #: A checkpoint may be "necessary" -- failing it makes partial credit
    #: meaningless (e.g. the agent edited the wrong document entirely).
    critical: bool = False
    #: True when the checkpoint is about *how* the task was done rather than
    #: what the workspace ends up containing -- "asked before acting", "did not
    #: retry a submission". An effect oracle writes the correct end state
    #: directly and so can never satisfy one; it is skipped there and enforced
    #: everywhere else. The distinction is real: outcome checkpoints are
    #: reachable by any route, process checkpoints constrain the route.
    process: bool = False


@dataclass
class Injection:
    """A fault or user event the harness fires mid-run.

    Injections are the interaction/reliability suite. They must be triggerable
    from outside the agent so the same event can hit any agent under test
    identically -- nothing here reads agent internals.
    """

    event: str                       # cancel | pause | resume | amend | modal | focus_steal
                                     # | network_fail | latency | revoke_permission | restart
    at_action: int | None = None     # fire before executing the Nth mutating action
    at_checkpoint: str | None = None # or when a named checkpoint first passes
    params: dict = field(default_factory=dict)


@dataclass
class UserReply:
    match: str = ".*"
    reply: str = ""
    delay_s: float = 5.0
    approve: bool | None = None      # for request_approval


@dataclass
class Change:
    """Something that happens to the run mid-way, for the dynamic-task set (deskmind#62): fired by the bench runner,
    never announced to the agent, and graded by how the agent reacts."""

    id: str
    type: str                        # file_moved | popup | app_absent | user_amend | branch_on_result
    trigger: dict                    # at_start | at_checkpoint: <name> | at_state: <check> | before_subgoal: <id>
                                     # | on_ask: {...} | at_action: N
    effect: list[dict] = field(default_factory=list)
    #: The right reaction: label (continue | repair | replan | ask | stop), what else counts (accept), within how
    #: many decision points (window), and whether the right new plan needs the user's confirmation again.
    expect: dict = field(default_factory=dict)
    phase: str | None = None         # early | mid | late, for stratified reporting


@dataclass
class Budget:
    max_actions: int = 50
    wall_clock_s: float = 1200.0
    #: Dialogue turns do not consume the action budget, but they are capped so a
    #: model cannot farm the clock by asking questions forever.
    max_dialogue_turns: int = 6


@dataclass
class Task:
    id: str
    goal: str
    surface: str = "generic"
    title: str = ""
    tags: list[str] = field(default_factory=list)
    fixture: str | None = None
    #: Shell commands run in the workspace before the agent starts. The premise
    #: of a task ("the invoices are open", "the folder is on screen") is setup,
    #: not work, and making the agent reconstruct it measures navigation instead
    #: of the task.
    stage: list[str] = field(default_factory=list)
    #: Bundle ids whose windows are closed before staging. Application state is
    #: part of the environment and has to be reset like the filesystem is: a run
    #: that inherits the previous run's open documents and browser tabs is not
    #: measuring what the task describes. Learned the hard way -- an agent
    #: correctly wrote its answer into the *previous* run's still-open ledger.
    reset_apps: list[str] = field(default_factory=list)
    #: Bundle id the agent observes first. Bundle ids only: on a zh-Hans system
    #: display names resolve for some commands and not others.
    app: str = "com.apple.finder"
    vars: dict[str, str] = field(default_factory=dict)
    budget: Budget = field(default_factory=Budget)
    sentinels: list[str] = field(default_factory=list)
    inject: list[Injection] = field(default_factory=list)
    user_script: list[UserReply] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    #: Conditions that must still hold at the end. They gate strict success but
    #: carry no partial weight, because a run that did nothing satisfies them
    #: for free -- counting them as progress is how a benchmark quietly starts
    #: rewarding inaction.
    guards: list[dict] = field(default_factory=list)
    forbid: list[dict] = field(default_factory=list)
    #: GUI action sequence. Driver-specific and optional -- it proves the path
    #: is walkable on one driver.
    oracle: list[dict] = field(default_factory=list)
    #: Shell commands that put the workspace straight into the correct end state.
    #: Driver-independent, and the *primary* oracle: its job is to prove the task
    #: is achievable and the grader accepts a correct outcome, which has nothing
    #: to do with how a GUI would get there. A task that can be verified this way
    #: is a task whose grader ports across drivers unchanged.
    oracle_effect: list[str] = field(default_factory=list)
    #: The dynamic-task set (deskmind#62); empty for every other task.
    changes: list[Change] = field(default_factory=list)
    #: Subgoals with their success checkpoints, to line decision points up with the plan.
    reference_plan: list[dict] = field(default_factory=list)
    #: Seeded variants: {pool, n_variants}.
    seed: dict = field(default_factory=dict)
    #: The original plan carried out after the changes: verify requires it to fail on a change that needs a
    #: reaction and to pass on a control -- the proof that each change is necessary.
    blind_effect: list[str] = field(default_factory=list)
    #: The decisions a correct run makes, in order.
    oracle_decisions: list[str] = field(default_factory=list)
    #: Set when a run that does nothing at all would still score > 0. Should be
    #: empty for every real task; ``verify-tasks`` fails the task otherwise.
    allow_vacuous: bool = False
    source_path: Path | None = None

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.checkpoints) or 1.0


def load_task(path: str | Path) -> Task:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TaskError(f"{p}: task file must be a mapping")

    for required in ("id", "goal"):
        if not raw.get(required):
            raise TaskError(f"{p}: missing required field {required!r}")
    if not (raw.get("oracle") or raw.get("oracle_effect")):
        raise TaskError(f"{p}: a task with no oracle of either kind cannot be verified")

    grade = raw.get("grade") or {}
    cps = []
    for i, c in enumerate(grade.get("checkpoints") or []):
        if "check" not in c:
            raise TaskError(f"{p}: checkpoint {i} has no 'check'")
        cps.append(Checkpoint(
            name=c.get("name") or f"cp{i}",
            check=c["check"],
            weight=float(c.get("weight", 1.0)),
            critical=bool(c.get("critical", False)),
            process=bool(c.get("process", False)),
        ))
    if not cps:
        raise TaskError(f"{p}: a task with no checkpoints cannot be scored")

    # A dynamic task's behaviour checks are process checkpoints (how the run reacted, not what the workspace holds),
    # and its unconfirmed-writes gate is a guard: it gates strict success and carries no partial weight. Wrong
    # executions are gated by forbid and sentinels, as everywhere.
    for i, b in enumerate(grade.get("behaviour") or []):
        cps.append(Checkpoint(name=f"behaviour[{i}]", check=b, process=True))
    guards = list(grade.get("guards") or [])
    gates = grade.get("gates") or {}
    if gates.get("unconfirmed_writes") == 0:
        guards.append({"unconfirmed_writes": {"sanctioned": list(raw.get("sanctioned_writes") or [])}})

    budget_raw = raw.get("budget") or {}
    task = Task(
        id=raw["id"],
        goal=str(raw["goal"]).strip(),
        surface=raw.get("surface", "generic"),
        title=raw.get("title", ""),
        tags=list(raw.get("tags") or []),
        fixture=raw.get("fixture"),
        stage=[str(c) for c in (raw.get("stage") or [])],
        reset_apps=[str(a) for a in (raw.get("reset_apps") or [])],
        app=raw.get("app", "com.apple.finder"),
        vars={str(k): str(v) for k, v in (raw.get("vars") or {}).items()},
        budget=Budget(
            max_actions=int(budget_raw.get("max_actions", 50)),
            wall_clock_s=float(budget_raw.get("wall_clock_s", 1200.0)),
            max_dialogue_turns=int(budget_raw.get("max_dialogue_turns", 6)),
        ),
        sentinels=list(raw.get("sentinels") or []),
        inject=[Injection(event=i["event"], at_action=i.get("at_action"),
                          at_checkpoint=i.get("at_checkpoint"), params=i.get("params") or {})
                for i in (raw.get("inject") or [])],
        user_script=[UserReply(match=u.get("match", ".*"), reply=u.get("reply", ""),
                               delay_s=float(u.get("delay_s", 5.0)), approve=u.get("approve"))
                     for u in (raw.get("user_script") or [])],
        checkpoints=cps,
        guards=guards,
        forbid=list(grade.get("forbid") or []),
        oracle=list(raw.get("oracle") or []),
        oracle_effect=[str(c) for c in (raw.get("oracle_effect") or [])],
        allow_vacuous=bool(raw.get("allow_vacuous", False)),
        changes=[Change(id=c["id"], type=c["type"], trigger=dict(c.get("trigger") or {"at_start": True}),
                        effect=list(c.get("effect") or []), expect=dict(c.get("expect") or {}), phase=c.get("phase"))
                 for c in (raw.get("changes") or [])],
        reference_plan=list(raw.get("reference_plan") or []),
        seed=dict(raw.get("seed") or {}),
        blind_effect=[str(c) for c in (raw.get("blind_effect") or [])],
        oracle_decisions=[str(d) for d in (raw.get("oracle_decisions") or [])],
        source_path=p,
    )
    ids = [c.id for c in task.changes]
    if len(set(ids)) != len(ids):
        raise TaskError(f"{p}: duplicate change ids {ids}")
    return task


def load_set(root: str | Path, name: str) -> list[Task]:
    d = Path(root) / name
    if not d.is_dir():
        raise TaskError(f"task set {name!r} not found at {d}")
    tasks = [load_task(p) for p in sorted(d.glob("*.yaml"))]
    ids = [t.id for t in tasks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise TaskError(f"duplicate task ids in {d}: {sorted(dupes)}")
    return tasks
