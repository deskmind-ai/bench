"""The Tier O orchestrator loop (#60): plan, confirm, run a part, check, decide; journal everything (#62 schema v1)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import signals as sig
from .decide import Context, by_code
from .events import EventLog
from .plan import Plan


@dataclass
class Budget:
    max_actions: int = 60
    max_replans: int = 3
    max_repairs_per_part: int = 1
    max_dialogue_turns: int = 3


def _parts(plan: Plan, now: str | None) -> list[dict]:
    return [{"id": s.id, "goal": s.goal, "status": "done" if s.id in plan.done else "now" if s.id == now else "todo"}
            for s in plan.subgoals]


def _new_writes(plan: Plan, confirmed: list[dict]) -> list[dict]:
    seen = {(w["op"], w["src"], w["dst"]) for w in confirmed}
    return [w for w in plan.writes() if (w["op"], w["src"], w["dst"]) not in seen]


def _confirm(plan: Plan, confirmed: list[dict], user, log: EventLog, turns: list[int], hooks) -> bool:
    """Ask the user to confirm the plan's writes that have not been confirmed yet (#60: a revised plan that adds a
    write, a delete or a send is shown again). Nothing new: no question."""
    new = _new_writes(plan, confirmed)
    if not new:
        return True
    lines = [f"- {w['op']}: {w['src'] or ''}{' → ' + w['dst'] if w['dst'] else ''}" for w in new]
    text = f"计划（第 {plan.version} 版）要做这些改动：\n" + "\n".join(lines) + "\n可以吗？"
    log.ask("plan_confirm", text, ["可以", "不要"])
    hooks.on_ask("plan_confirm", text)
    reply, ok, slot = user.respond(text, approval=True)
    log.user_msg("reply", reply, slot)
    turns[0] += 1
    log.plan_confirmed(plan.version, ok, reply)
    if ok:
        confirmed.extend(new)
    return ok


class NoHooks:
    """Where a bench runner fires a task's changes (runner.ChangeHooks). The orchestrator itself knows nothing of
    them: it calls these at fixed points and carries on with whatever the world now is."""

    def at_start(self) -> None: ...
    def before_subgoal(self, k: int, clause: str) -> None: ...
    def after_subgoal(self) -> None: ...
    def on_ask(self, kind: str, text: str) -> None: ...


def run(goal: str, ws: Path | None, *, planner, decider, executor, user, log: EventLog, budget: Budget = Budget(),
        channel: str = "gui", can_handoff: bool = False, apps: list[str] | None = None, check_apps: bool = False,
        hooks=None) -> dict:
    hooks = hooks or NoHooks()
    hooks.at_start()
    started: list[str] = []          # clauses in the order they were first started: before_subgoal's k
    plan = planner.plan(goal, channel)
    said: list[str] = []
    log.plan_proposed(plan.version, planner.by, [s.to_event() for s in plan.subgoals], plan.writes())
    confirmed: list[dict] = []
    turns = [0]
    if not _confirm(plan, confirmed, user, log, turns, hooks):
        return log.done("stopped", "用户没有同意计划，什么都没做。")
    used, replans, repairs, done_goals, skipped, total_parts = 0, 0, {}, [], [], len(plan.subgoals)
    i = 0
    while True:
        todo = plan.remaining()
        if not todo:
            if skipped:   # moved on past a part that was not met: the task is not done, and the report says which
                return log.done("failed", f"没有完成：{'；'.join(skipped)}；已完成：{'；'.join(done_goals) or '无'}")
            return log.done("completed", "完成：" + "；".join(done_goals))
        sg = todo[0]
        left = max(budget.max_actions - used, 0)
        if left == 0:
            return log.done("failed", f"动作预算用完；已完成：{'；'.join(done_goals) or '无'}")
        per = max(min(left, -(-left // len(todo)) + 4), 1)
        if sg.clause not in started:
            started.append(sg.clause)
            hooks.before_subgoal(len(started), sg.clause)
        log.subgoal_start(sg.id, plan.version, sg.channel, per)
        res = executor.run(sg, ws, per, user, log, plan.constraints)
        used += res.steps
        hooks.after_subgoal()                   # a change waiting on a state fires now, before anything is decided
        if res.outcome == "met":
            plan.done.append(sg.id)
            done_goals.append(sg.clause)
        heard = user.interjections()
        for h in heard:
            log.user_msg("interject", h, None)
        said += heard
        sigs = sig.detect(outcome=res.outcome, detail=res.detail, plan=plan, ws=ws, interjections=heard,
                          actions_used=used, actions_total=budget.max_actions, parts_done=len(done_goals),
                          parts_total=total_parts, apps=apps, check_apps=check_apps)
        log.subgoal_end(sg.id, plan.version, res.outcome, sigs, res.steps, res.hands_run, res.model_calls)
        ctx = Context(goal=goal, plan_version=plan.version, parts=_parts(plan, sg.id), outcome=res.outcome,
                      detail=res.detail, signals=sigs, said=list(said),
                      can_repair=res.outcome != "met" and repairs.get(sg.id, 0) < budget.max_repairs_per_part,
                      can_replan=replans < budget.max_replans,
                      can_ask=turns[0] < budget.max_dialogue_turns, can_handoff=can_handoff)
        choice = by_code(ctx)
        if choice:
            log.decision(choice, plan.version, sigs, "code", ctx.options(), None)
            continue
        choice, probs, by = decider.decide(ctx)
        log.decision(choice, plan.version, sigs, by, ctx.options(), probs)
        if choice == "continue":
            if res.outcome != "met":           # moved on without it: not tried again, and the run cannot complete
                plan.done.append(sg.id)
                skipped.append(sg.clause)
            continue
        if choice == "repair":
            repairs[sg.id] = repairs.get(sg.id, 0) + 1
            # The same part again, told what went wrong last time (a signal name and the run's last words).
            sg.goal = f"{sg.goal}（上一次没有成功：{', '.join(sigs) or res.outcome}）"
            continue
        if choice == "replan":
            replans += 1
            plan = planner.replan(goal, plan, said)
            total_parts = len(done_goals) + len(skipped) + len(plan.subgoals)
            log.plan_proposed(plan.version, planner.by, [s.to_event() for s in plan.subgoals], plan.writes())
            if not _confirm(plan, confirmed, user, log, turns, hooks):
                return log.done("stopped", f"用户没有同意修改后的计划；已完成：{'；'.join(done_goals) or '无'}")
            continue
        if choice == "ask":
            text = f"「{sg.goal}」没有按预期完成（{', '.join(sigs) or res.outcome}）。接下来怎么办？"
            log.ask("clarify", text, [])
            hooks.on_ask("clarify", text)
            reply, _, slot = user.respond(text)
            log.user_msg("reply", reply, slot)
            turns[0] += 1
            said.append(reply)
            if sg.id not in plan.done:          # the part is tried again with the user's answer
                sg.goal = f"{sg.goal}（用户说：{reply}）"
            continue
        if choice == "handoff":
            return log.done("handoff", f"交给云端模型；已完成：{'；'.join(done_goals) or '无'}")
        return log.done("stopped", f"停下：{', '.join(sigs) or res.outcome}；已完成：{'；'.join(done_goals) or '无'}")
