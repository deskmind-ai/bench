"""The Tier O orchestrator prototype (deskmind#60, #62), offline: a function executor stands in for hands, a scripted
decider for the Brain, and the scripted user answers. No desktop, no model.

    python -m unittest tests.test_dyn_proto -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from deskmind_bench.dyn.proto.decide import ScriptedDecider            # noqa: E402
from deskmind_bench.dyn.proto.events import EventLog, read             # noqa: E402
from deskmind_bench.dyn.proto.executors import FnExecutor, Result      # noqa: E402
from deskmind_bench.dyn.proto.orchestrator import Budget, run          # noqa: E402
from deskmind_bench.dyn.proto.plan import TemplatePlanner              # noqa: E402
from deskmind_bench.dyn.proto.signals import where_expected            # noqa: E402
from deskmind_bench.dyn.proto.user import ScriptedUser                 # noqa: E402

GOAL = "新建文件夹 资料，把 draft-21.csv 放进去；然后把 todo-94.txt 改名为 会议纪要-2.txt；最后把 backup 里的 记录-30.txt 移到顶层。其他文件不要动。"


def files_ws(*names: str) -> Path:
    ws = Path(tempfile.mkdtemp())
    for n in names:
        (ws / n).parent.mkdir(parents=True, exist_ok=True)
        (ws / n).write_text(n)
    return ws


def executor(effects: dict | None = None):
    """Each part "succeeds" if the first file it names exists; `effects` runs a change after a part (by index)."""
    calls = []

    def fn(sg, ws, max_actions):
        import re
        calls.append(sg.goal)
        names = re.findall(r"[\w一-鿿.\-]+\.[a-z]{2,4}", sg.goal)
        ok = not names or where_expected(sg.goal, names[0], ws)
        if effects and len(calls) in effects:
            effects[len(calls)](ws)
        return Result("met" if ok else "unmet", steps=3, detail="" if ok else f"{names[0]} not found")
    fn.calls = calls
    return fn


class Orchestrator(unittest.TestCase):
    def go(self, ws, fn, decide, user=None, budget=Budget()):
        log_path = Path(tempfile.mkdtemp()) / "orchestrator.jsonl"
        log = EventLog(log_path, "t1")
        out = run(GOAL, ws, planner=TemplatePlanner(), decider=ScriptedDecider(decide), executor=FnExecutor(fn),
                  user=user or ScriptedUser(), log=log, budget=budget)
        return out, read(log_path)

    def test_the_template_planner_splits_the_parts_and_keeps_the_constraint(self):
        plan = TemplatePlanner().plan(GOAL)
        self.assertEqual([s.goal for s in plan.subgoals],
                         ["新建文件夹 资料，把 draft-21.csv 放进去", "把 todo-94.txt 改名为 会议纪要-2.txt", "把 backup 里的 记录-30.txt 移到顶层"])
        self.assertEqual(plan.constraints, "其他文件不要动。")
        self.assertEqual([w["op"] for w in plan.writes()], ["mkdir", "rename", "move"])

    def test_clean_run_decides_by_code_and_never_calls_the_model(self):
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        out, ev = self.go(ws, executor(), lambda ctx: self.fail("model asked on a clean run"))
        self.assertEqual(out["state"], "completed")
        self.assertEqual([e["by"] for e in ev if e["t"] == "decision"], ["code"] * 3)
        self.assertEqual([e["t"] for e in ev][:3], ["plan_proposed", "ask", "user_msg"])   # confirmed before any write
        self.assertTrue(next(e for e in ev if e["t"] == "plan_confirmed")["approved"])

    def test_a_moved_file_is_a_signal_and_the_model_decides(self):
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        move = {1: lambda ws: (ws / "old").mkdir() or (ws / "todo-94.txt").rename(ws / "old" / "todo-94.txt")}
        seen = []

        def decide(ctx):
            seen.append(ctx.signals)
            return "ask" if "file_missing" in ctx.signals and ctx.can_ask else "stop"
        user = ScriptedUser([{"slot": "where", "match": "接下来怎么办|没有按预期", "reply": "在 old 文件夹里"}])
        out, ev = self.go(ws, executor(move), decide, user)
        self.assertIn("file_missing", seen[0])
        d = [e for e in ev if e["t"] == "decision"]
        self.assertEqual(d[0]["choice"], "ask")
        self.assertEqual(d[0]["options"], ["continue", "replan", "ask", "stop"])   # part 1 was met: no repair
        self.assertIn({"t": "user_msg", "kind": "reply", "text": "在 old 文件夹里", "slot": "where"},
                      [{k: e[k] for k in ("t", "kind", "text", "slot")} for e in ev if e["t"] == "user_msg"])

    def test_a_replan_that_adds_a_write_is_confirmed_again(self):
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        queue = Path(tempfile.mkdtemp()) / "user_queue.jsonl"
        add = {1: lambda ws: queue.write_text(json.dumps({"text": "再把 清单-87.log 删除"}, ensure_ascii=False) + "\n")}
        decide = lambda ctx: "replan" if "user_interjected" in ctx.signals else "continue"
        out, ev = self.go(ws, executor(add), decide, ScriptedUser(queue=queue))
        versions = [e["version"] for e in ev if e["t"] == "plan_proposed"]
        self.assertEqual(versions, [1, 2])
        confirms = [e for e in ev if e["t"] == "plan_confirmed"]
        self.assertEqual([c["version"] for c in confirms], [1, 2], "the new delete is shown again")
        self.assertIn("delete", next(e for e in ev if e["t"] == "ask" and "第 2 版" in e["text"])["text"])

    def test_a_replan_with_nothing_new_to_write_asks_nothing(self):
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        queue = Path(tempfile.mkdtemp()) / "q.jsonl"
        say = {1: lambda ws: queue.write_text(json.dumps({"text": "慢一点"}, ensure_ascii=False) + "\n")}
        decide = lambda ctx: "replan" if "user_interjected" in ctx.signals else "continue"
        _, ev = self.go(ws, executor(say), decide, ScriptedUser(queue=queue))
        self.assertEqual([c["version"] for c in ev if c["t"] == "plan_confirmed"], [1])

    def test_declined_plan_does_nothing(self):
        ws = files_ws("draft-21.csv")
        fn = executor()
        out, ev = self.go(ws, fn, lambda ctx: "continue", ScriptedUser(approve_plans=False))
        self.assertEqual(out["state"], "stopped")
        self.assertEqual(fn.calls, [])

    def test_replans_are_capped(self):
        ws = files_ws()
        _, ev = self.go(ws, executor(), lambda ctx: "replan" if ctx.can_replan else "stop", budget=Budget(max_replans=2))
        self.assertEqual(sum(1 for e in ev if e["t"] == "decision" and e["choice"] == "replan"), 2)
        self.assertEqual(ev[-1]["state"], "stopped")
        self.assertNotIn("replan", [e for e in ev if e["t"] == "decision"][-1]["options"])

    def test_repair_retries_once_with_what_went_wrong(self):
        ws = files_ws("todo-94.txt", "backup/记录-30.txt")      # draft-21.csv missing: part 1 fails
        fn = executor()
        _, ev = self.go(ws, fn, lambda ctx: "repair" if ctx.can_repair else "stop")
        self.assertEqual(len(fn.calls), 2)
        self.assertIn("上一次没有成功", fn.calls[1])
        self.assertEqual([e["choice"] for e in ev if e["t"] == "decision"], ["repair", "stop"])

    def test_every_event_carries_the_envelope(self):
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        _, ev = self.go(ws, executor(), lambda ctx: "continue")
        for e in ev:
            self.assertEqual((e["v"], e["run"]), (1, "t1"))
            self.assertIsInstance(e["ts"], float)
        self.assertEqual([e["dp"] for e in ev if e["t"] == "decision"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
