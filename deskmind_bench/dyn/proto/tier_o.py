"""Tier O runner (#62): one dyn task, one arm, one run, offline -- then graded by bench's own grader.

    python -m deskmind_bench.dyn.proto.tier_o <task.yaml> --arm c --out runs/t7/D-FM1-dev/c-r1 \\
        --text-url http://127.0.0.1:8899 --systemone-url http://127.0.0.1:8796 [--frontier-model openai/...]

Arms (the T7 preregistration on deskmind#62):
  a  stepwise, no plan: each step the local model gives the next operation, "done" or one question (StepwiseAgent)
  b  fixed plan: ModelPlanner (local), every decision "continue"
  c  dynamic, local: ModelPlanner (local), decisions by the local Brain over /v1/systemone
  d  dynamic, frontier planning: ModelPlanner with a frontier model (synthetic workspaces only, #33 / #54)
  t  reference: TemplatePlanner, decisions as in c (outside the pass rule)
Every arm's file writes go through code: declared writes (DeclaredWritesExecutor), else an operation list written
by the local model (OpListExecutor). Changes fire through ChangeHooks; the user is ScriptedUser with the task's
user_script. The frontier key is read from the environment (OPENROUTER_API_KEY), never from a file or an argument.

Writes <out>/ws (the workspace), <out>/run (orchestrator.jsonl, changes.jsonl, traces) and <out>/result.json: the
grade, every decision with its probabilities (calibration), model calls by tier, wall time.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from ...graders.primitives import GradeContext, evaluate
from ...graders.score import grade
from ...scoring import pristine_sentinels
from ...task import load_task
from ...verify import NULL_METRICS, _unpack
from .. import events as ev
from . import oplist
from .decide import ScriptedDecider, SystemOneDecider
from .events import EventLog
from .oplist import DeclaredWritesExecutor, HttpTextPlanner, OpListExecutor
from .orchestrator import Budget, run
from .plan import TemplatePlanner
from .plan_model import ModelPlanner, openai_chat
from .runner import ChangeHooks
from .user import ScriptedUser

BENCH = Path(__file__).resolve().parents[3]

STEP = """你在一个工作目录里完成用户交给你的文件任务，一次只做一步。你不直接动文件：每一步只回答一个 JSON 对象，由程序检查后执行。

可以回答的四种：
{{"op": "mkdir", "path": "相对路径"}}
{{"op": "move", "from": "相对路径", "to": "相对路径"}}      改名也用 move；"to" 是完整的新路径
{{"done": "一句话汇报做了什么"}}                          任务做完了，或者没有可做的
{{"ask": "向用户提的一个问题"}}                            缺信息时

规则：不能删除，不能覆盖已有文件；只做用户要求的事，别的文件不要动。只输出一个 JSON 对象。

用户的要求：
{goal}

用户说过的话：
{said}

已经做过的操作：
{history}

工作目录现在的内容（以 / 结尾的是文件夹）：
{listing}
{contents}"""


def peek(ws: Path, max_bytes: int = 1024, max_files: int = 20) -> str:
    """The text of small files, as ModelPlanner(peek_bytes) shows them; for workspaces the bench generates only."""
    shown = []
    for p in sorted(ws.rglob("*")):
        rel = p.relative_to(ws).as_posix()
        if len(shown) >= max_files or p.is_dir() or any(x.startswith(".") for x in Path(rel).parts):
            continue
        try:
            if p.stat().st_size <= max_bytes:
                shown.append(f"--- {rel}\n{p.read_text(encoding='utf-8').rstrip()}")
        except (OSError, UnicodeDecodeError):
            continue
    return ("\n小文本文件的内容：\n" + "\n".join(shown) + "\n") if shown else ""


class StepwiseAgent:
    """Arm (a): today's way, without a plan. One model call per step; code checks and carries out the one operation.
    Its writes and questions go to <run>/trace.jsonl in the harness's record shape, so the dyn graders read them as
    they read hands' (write_steps, asks)."""

    def __init__(self, complete, run_dir: Path, max_actions: int, max_turns: int) -> None:
        self.complete, self.run_dir, self.max_actions, self.max_turns = complete, Path(run_dir), max_actions, max_turns
        self.calls = 0

    def run(self, task, ws: Path, user: ScriptedUser, log: EventLog, hooks: ChangeHooks) -> dict:
        trace = self.run_dir / "trace.jsonl"
        trace.touch()

        def rec(r: dict) -> None:
            with trace.open("a", encoding="utf-8") as f:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        history, said, turns, n = [], [], 0, 0
        order = [p.get("id") for p in task.reference_plan]
        posts = {c.name: c for c in task.checkpoints}
        ctx = GradeContext(workspace=ws, vars=task.vars, run=hooks.run_info)

        def parts_done(k: int) -> bool:   # the reference plan's first k parts all pass their checkpoints
            return all(evaluate(posts[p["post"]].check, ctx).ok for p in task.reference_plan[:k] if p.get("post") in posts)

        def fire_due() -> None:
            hooks.after_subgoal()
            for c in hooks._pending("before_subgoal"):
                ref = c.trigger["before_subgoal"]
                if ref in order and parts_done(order.index(ref)):
                    hooks._fire(c)
            said.extend(user.interjections())

        hooks.at_start()
        fire_due()
        report, state = "", "failed"
        while n < self.max_actions:
            n += 1
            prompt = STEP.format(goal=task.goal, said="\n".join(f"- {s}" for s in said) or "（无）",
                                 history="\n".join(history) or "（无）", listing=oplist.listing(ws), contents=peek(ws))
            t0 = time.time()
            self.calls += 1
            reply = self.complete([{"role": "user", "content": prompt}])
            t1 = time.time()
            try:
                obj = json.loads(reply[reply.find("{"): reply.rfind("}") + 1])
            except (ValueError, json.JSONDecodeError):
                rec({"t": "step", "n": n, "ok": False, "kind": "parse_error", "detail": reply[:200], "t_decide_end": t1})
                history.append(f"{n}. （回答不是 JSON，没有执行）")
                continue
            if "done" in obj:
                report, state = str(obj["done"]), "completed"
                rec({"t": "step", "n": n, "ok": True, "kind": "done", "detail": report, "t_decide_end": t1})
                break
            if "ask" in obj:
                if turns >= self.max_turns:
                    report, state = f"问题太多，停下：{obj['ask']}", "stopped"
                    break
                reply_text, _, slot = user.respond(str(obj["ask"]))
                turns += 1
                said.append(reply_text)
                rec({"t": "step", "n": n, "ok": True, "kind": "ask_user", "detail": str(obj["ask"]), "reply": reply_text,
                     "t_decide_end": t1, "t_reply": time.time()})
                history.append(f"{n}. 问用户：{obj['ask']} → {reply_text}")
                continue
            try:
                steps = oplist.dry_run([obj], ws)
            except ValueError as exc:
                rec({"t": "step", "n": n, "ok": False, "kind": "refused", "detail": str(exc), "t_decide_end": t1})
                history.append(f"{n}. {json.dumps(obj, ensure_ascii=False)} → 被拒绝：{exc}")
                continue
            oplist.carry_out(steps, ws, trace)
            history.append(f"{n}. {json.dumps(obj, ensure_ascii=False)} → 已执行")
            fire_due()
            del t0
        else:
            report, state = "动作预算用完", "failed"
        log.done(state, report or "（没有汇报）")
        return {"state": state, "report": report, "steps": n}


class SafeHooks(ChangeHooks):
    """A change whose effect can no longer apply (its source was already moved by the run) is recorded as skipped in
    <run>/skipped_changes.jsonl rather than ending the run; the task's behaviour checks then see it never fired."""

    def _fire(self, change) -> None:
        try:
            super()._fire(change)
        except (FileNotFoundError, shutil.Error, OSError) as exc:
            self.injector.fired.add(change.id)
            with (self.run_dir / "skipped_changes.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"change_id": change.id, "why": f"{type(exc).__name__}: {exc}"[:300]}, ensure_ascii=False) + "\n")


def _slots(task) -> list[dict]:
    return [{"slot": f"s{i}", "match": u.match, "reply": u.reply, **({"approve": u.approve} if u.approve is not None else {})}
            for i, u in enumerate(task.user_script)]


def run_one(task_path: Path, arm: str, out: Path, *, text_url: str = "http://127.0.0.1:8899",
            systemone_url: str = "http://127.0.0.1:8796", frontier_model: str | None = None,
            frontier_url: str = "https://openrouter.ai/api/v1", fixtures: Path | None = None,
            local_chat=None, text=None, decider=None) -> dict:
    """local_chat / text / decider replace the HTTP backends (tests)."""
    task = load_task(task_path)
    fixtures = Path(fixtures) if fixtures else BENCH / "fixtures"
    if out.exists():
        shutil.rmtree(out)
    run_dir = out / "run"
    run_dir.mkdir(parents=True)
    ws = _unpack(task, fixtures, out)
    run_id = f"{task.id}:{arm}:{out.name}"
    fixture_dir = fixtures / task.fixture
    hooks = SafeHooks(task, ws, run_dir, run_id, fixture_dir=fixture_dir)
    user = ScriptedUser(_slots(task), queue=run_dir / "user_queue.jsonl")
    log = EventLog(run_dir / "orchestrator.jsonl", run_id)
    (run_dir / "changes.jsonl").touch()
    local_chat = local_chat or openai_chat(text_url.rstrip("/") + "/v1", "local-4b", max_tokens=1500)
    text = text or HttpTextPlanner(text_url.rstrip("/"), kind="prompt")
    budget = Budget(max_actions=task.budget.max_actions, max_dialogue_turns=task.budget.max_dialogue_turns)
    t0 = time.time()
    calls = {"plan_local": 0, "plan_cloud": 0, "oplist_local": 0, "step_local": 0}
    if arm == "a":
        agent = StepwiseAgent(local_chat, run_dir, task.budget.max_actions, task.budget.max_dialogue_turns)
        try:
            outcome = agent.run(task, ws, user, log, hooks)
        finally:
            hooks.close()
        calls["step_local"] = agent.calls
    else:
        if arm == "d":
            if not frontier_model:
                raise SystemExit("arm d needs --frontier-model")
            key = os.environ.get("OPENROUTER_API_KEY")
            planner = ModelPlanner(openai_chat(frontier_url, frontier_model, api_key=key, max_tokens=2000), by="frontier",
                                   peek_bytes=1024)
        elif arm == "t":
            planner = TemplatePlanner()
        else:
            planner = ModelPlanner(local_chat, by="local-4b", peek_bytes=1024)
        decider = (ScriptedDecider(lambda ctx: "continue", by="code") if arm == "b"
                   else decider or SystemOneDecider(systemone_url))
        executor = DeclaredWritesExecutor(run_dir, fallback=OpListExecutor(text, run_dir))
        outcome = run(task.goal, ws, planner=planner, decider=decider, executor=executor, user=user, log=log, budget=budget,
                      channel="oplist", hooks=hooks)
        calls["plan_cloud" if arm == "d" else "plan_local"] = getattr(planner, "calls", 0)
        calls["oplist_local"] = getattr(text, "calls", 0)
    wall = time.time() - t0
    orch, changes = ev.run_events(run_dir)
    g = grade(task, GradeContext(workspace=ws, vars=task.vars,
                                 run={"state": outcome.get("state"), "metrics": dict(NULL_METRICS), "dir": str(run_dir),
                                      "fixture_dir": str(fixture_dir), "report": outcome.get("report")}),
              sentinel_digests=pristine_sentinels(task, fixtures))
    decisions = [{k: e.get(k) for k in ("dp", "choice", "by", "options", "probabilities", "signals", "ts")}
                 for e in orch if e["t"] == "decision"]
    result = {"task": task.id, "arm": arm, "run": out.name, "state": outcome.get("state"), "report": outcome.get("report"),
              "strict": bool(g.strict), "partial": round(g.partial, 3),
              "checkpoints": {k: v.ok for k, v in g.checkpoints.items()}, "violations": [str(v) for v in g.violations],
              "changes": [{k: c.get(k) for k in ("change_id", "type", "ts")} for c in changes],
              "expect": {c.id: c.expect for c in task.changes}, "decisions": decisions,
              "asks": [e.get("kind") for e in orch if e["t"] == "ask"], "calls": calls, "wall_s": round(wall, 2),
              "skipped_changes": [json.loads(l) for l in (run_dir / "skipped_changes.jsonl").read_text().splitlines()]
              if (run_dir / "skipped_changes.jsonl").exists() else []}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m deskmind_bench.dyn.proto.tier_o")
    ap.add_argument("task", type=Path)
    ap.add_argument("--arm", required=True, choices=list("abcdt"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--text-url", default="http://127.0.0.1:8899")
    ap.add_argument("--systemone-url", default="http://127.0.0.1:8796")
    ap.add_argument("--frontier-model", default=None)
    args = ap.parse_args(argv)
    r = run_one(args.task, args.arm, args.out, text_url=args.text_url, systemone_url=args.systemone_url,
                frontier_model=args.frontier_model)
    print(json.dumps({k: r[k] for k in ("task", "arm", "state", "strict", "partial", "violations", "calls", "wall_s")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
