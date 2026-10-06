"""OpListExecutor (Tier O, #62): the dry run, the one retry with the reason, the write records the dyn graders read,
and the orchestrator running a task's parts with it."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deskmind_bench import dyn  # noqa: F401
from deskmind_bench.dyn.graders import write_steps
from deskmind_bench.dyn.proto import oplist
from deskmind_bench.dyn.proto.events import EventLog
from deskmind_bench.dyn.proto.executors import OpListExecutor
from deskmind_bench.dyn.proto.orchestrator import run
from deskmind_bench.dyn.proto.plan import Subgoal, TemplatePlanner
from deskmind_bench.dyn.proto.user import ScriptedUser


def ws_with(*names: str) -> Path:
    ws = Path(tempfile.mkdtemp(prefix="oplist-test-"))
    for n in names:
        (ws / n).parent.mkdir(parents=True, exist_ok=True)
        if not n.endswith("/"):
            (ws / n).write_text(Path(n).name + "\n")
    return ws


class Planner:
    """Replies in turn; records every prompt."""

    def __init__(self, *replies: str) -> None:
        self.replies, self.prompts = list(replies), []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def ops(*o) -> str:
    return json.dumps(list(o), ensure_ascii=False)


class DryRun(unittest.TestCase):
    def test_refuses_what_cannot_be_carried_out_and_touches_nothing(self):
        ws = ws_with("a.txt", "b.txt", "sub/")
        before = oplist.listing(ws)
        for bad, why in ((ops({"op": "move", "from": "../x", "to": "y"}), "离开工作目录"),
                         (ops({"op": "move", "from": "a.txt", "to": "b.txt"}), "不能覆盖"),
                         (ops({"op": "move", "from": "nope.txt", "to": "c.txt"}), "不存在"),
                         (ops({"op": "delete", "path": "a.txt"}), "只能用 mkdir 和 move"),
                         (ops({"op": "move", "from": "a.txt", "to": "missing/a.txt"}), "文件夹不存在")):
            with self.assertRaisesRegex(ValueError, why):
                oplist.dry_run(oplist.parse(bad), ws)
        self.assertEqual(oplist.listing(ws), before)

    def test_a_missing_final_bracket_is_closed_and_nothing_else_is_repaired(self):
        self.assertEqual(oplist.parse('[{"op": "mkdir", "path": "x"}<|im_end|>'), [{"op": "mkdir", "path": "x"}])
        with self.assertRaises(ValueError):
            oplist.parse('["mkdir", "x"]')
        with self.assertRaises(ValueError):
            oplist.parse("no list here")


class Executor(unittest.TestCase):
    def go(self, ws, planner, goal="新建文件夹 资料，把 a.txt 放进去"):
        run_dir = Path(tempfile.mkdtemp())
        res = OpListExecutor(planner, run_dir).run(Subgoal("part1", goal), ws, 10, None, None)
        return res, run_dir

    def test_a_list_that_passes_is_carried_out_and_recorded_as_writes(self):
        ws = ws_with("a.txt")
        res, run_dir = self.go(ws, Planner(ops({"op": "mkdir", "path": "资料"}, {"op": "move", "from": "a.txt", "to": "资料/a.txt"})))
        self.assertEqual((res.outcome, res.steps, res.model_calls), ("met", 2, {"local": 1, "cloud": 0}))
        self.assertTrue((ws / "资料" / "a.txt").exists())
        orch = [{"t": "subgoal_end", "hands_run": res.hands_run}]
        self.assertEqual([w["detail"] for w in write_steps(run_dir, orch)],
                         ["created folder '资料'", "moved 'a.txt' to '资料/a.txt'"])

    def test_a_refused_list_is_retried_once_with_the_reason_then_unmet(self):
        ws = ws_with("a.txt")
        p = Planner(ops({"op": "move", "from": "x.txt", "to": "y.txt"}), ops({"op": "move", "from": "x.txt", "to": "y.txt"}))
        res, run_dir = self.go(ws, p)
        self.assertEqual(res.outcome, "unmet")
        self.assertIn("不存在", res.detail)
        self.assertEqual(len(p.prompts), 2)
        self.assertIn("没有通过检查", p.prompts[1])
        self.assertEqual(write_steps(run_dir, [{"t": "subgoal_end", "hands_run": res.hands_run}]), [])
        self.assertEqual(oplist.listing(ws), "a.txt")

    def test_the_planner_sees_the_listing_and_the_subgoal_only(self):
        ws = ws_with("a.txt", "keep/reference.txt")
        p = Planner(ops())
        self.go(ws, p, goal="把 a.txt 改名为 b.txt")
        self.assertIn("keep/reference.txt", p.prompts[0])
        self.assertIn("把 a.txt 改名为 b.txt", p.prompts[0])


class WithTheOrchestrator(unittest.TestCase):
    def test_three_parts_through_the_template_planner(self):
        ws = ws_with("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        goal = "先新建文件夹 资料，把 draft-21.csv 放进去；然后把 todo-94.txt 改名为 会议纪要-2.txt；最后把 backup 里的 记录-30.txt 移到顶层。"
        replies = [ops({"op": "mkdir", "path": "资料"}, {"op": "move", "from": "draft-21.csv", "to": "资料/draft-21.csv"}),
                   ops({"op": "move", "from": "todo-94.txt", "to": "会议纪要-2.txt"}),
                   ops({"op": "move", "from": "backup/记录-30.txt", "to": "记录-30.txt"})]
        run_dir = Path(tempfile.mkdtemp())

        class Continue:
            def decide(self, ctx):
                return "continue", None, "test"
        out = run(goal, ws, planner=TemplatePlanner(), decider=Continue(), executor=OpListExecutor(Planner(*replies), run_dir),
                  user=ScriptedUser(), log=EventLog(run_dir / "orchestrator.jsonl", "t1"), channel="oplist")
        self.assertEqual(out["state"], "completed")
        self.assertTrue((ws / "资料" / "draft-21.csv").exists() and (ws / "会议纪要-2.txt").exists() and (ws / "记录-30.txt").exists())
        orch = [json.loads(l) for l in (run_dir / "orchestrator.jsonl").read_text().splitlines()]
        self.assertEqual(len(write_steps(run_dir, orch)), 4)


if __name__ == "__main__":
    unittest.main()
