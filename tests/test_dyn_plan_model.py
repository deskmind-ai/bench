"""A model writes the plan, code checks it first (deskmind#60, T7's model-planner arms), offline: a scripted function
stands in for the model.

    python -m unittest tests.test_dyn_plan_model -v
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
from deskmind_bench.dyn.proto.orchestrator import run                  # noqa: E402
from deskmind_bench.dyn.proto.plan_model import ModelPlanner, dry_run, tree   # noqa: E402
from deskmind_bench.dyn.proto.signals import missing_files             # noqa: E402
from deskmind_bench.dyn.proto.user import ScriptedUser                 # noqa: E402

GOAL = "把这些文件按项目整理一下。其他文件不要动。"


def files_ws(*names: str) -> Path:
    ws = Path(tempfile.mkdtemp())
    for n in names:
        (ws / n).parent.mkdir(parents=True, exist_ok=True)
        (ws / n).write_text(n)
    return ws


def model(*replies):
    """Answers in order; records what it was sent."""
    seen = []

    def complete(messages):
        seen.append([dict(m) for m in messages])
        r = replies[len(seen) - 1]
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
    complete.seen = seen
    return complete


PLAN = {"parts": [
    {"goal": "新建文件夹「甲」，把 甲-预算.xlsx 放进去",
     "writes": [{"op": "mkdir", "dst": "甲"}, {"op": "move", "src": "甲-预算.xlsx", "dst": "甲/甲-预算.xlsx"}]},
    {"goal": "新建文件夹「乙」，把 乙-合同.pdf 放进去",
     "writes": [{"op": "mkdir", "dst": "乙"}, {"op": "move", "src": "乙-合同.pdf", "dst": "乙/乙-合同.pdf"}]}]}


def do_writes(sg, ws, max_actions):
    """A perfect executor: carries out the part's declared writes."""
    for w in sg.writes or []:
        if w["op"] == "mkdir":
            (ws / w["dst"]).mkdir()
        elif w["op"] == "move":
            (ws / w["src"]).rename(ws / w["dst"])
    return Result("met", steps=len(sg.writes or []))


class DryRun(unittest.TestCase):
    def test_a_good_plan_passes_in_order(self):
        files = {"a.txt", "b/"}
        self.assertTrue(dry_run([{"op": "mkdir", "dst": "c"}, {"op": "move", "src": "a.txt", "dst": "c/a.txt"},
                                 {"op": "move", "src": "c", "dst": "b/c"}], files).ok)

    def test_every_problem_is_listed_and_nothing_changes(self):
        files = {"a.txt", "b.txt"}
        r = dry_run([{"op": "move", "src": "x.txt", "dst": "y.txt"},
                     {"op": "move", "src": "a.txt", "dst": "b.txt"},
                     {"op": "move", "src": "a.txt", "dst": "nope/a.txt"},
                     {"op": "delete", "src": "../etc/passwd"},
                     {"op": "chmod", "src": "a.txt"}], files)
        self.assertFalse(r.ok)
        self.assertEqual(len(r.problems), 5, r.problems)
        self.assertEqual(files, {"a.txt", "b.txt"})

    def test_a_folder_moved_takes_its_files_with_it(self):
        r = dry_run([{"op": "move", "src": "b", "dst": "c"}, {"op": "move", "src": "c/x.txt", "dst": "x.txt"}],
                    {"b/", "b/x.txt"})
        self.assertTrue(r.ok, r.problems)


class Planner(unittest.TestCase):
    def go(self, complete, user=None, ws=None):
        ws = ws or files_ws("甲-预算.xlsx", "乙-合同.pdf", "readme.md")
        log_path = Path(tempfile.mkdtemp()) / "orchestrator.jsonl"
        fn_calls = []

        def fn(sg, ws, max_actions):
            fn_calls.append(sg.goal)
            return do_writes(sg, ws, max_actions)
        out = run(GOAL, ws, planner=ModelPlanner(complete), decider=ScriptedDecider(lambda ctx: "stop"),
                  executor=FnExecutor(fn), user=user or ScriptedUser(), log=EventLog(log_path, "t1"))
        return out, read(log_path), ws, fn_calls

    def test_the_declared_writes_are_what_the_user_confirms(self):
        out, ev, ws, _ = self.go(model(PLAN))
        self.assertEqual(out["state"], "completed", out)
        proposed = next(e for e in ev if e["t"] == "plan_proposed")
        self.assertEqual(proposed["by"], "local-4b")
        self.assertEqual([(w["op"], w["src"], w["dst"]) for w in proposed["writes"]],
                         [("mkdir", None, "甲"), ("move", "甲-预算.xlsx", "甲/甲-预算.xlsx"),
                          ("mkdir", None, "乙"), ("move", "乙-合同.pdf", "乙/乙-合同.pdf")])
        self.assertIn("甲-预算.xlsx", next(e for e in ev if e["t"] == "ask")["text"])
        self.assertTrue((ws / "甲" / "甲-预算.xlsx").exists())

    def test_the_model_sees_the_files_and_the_constraint(self):
        m = model(PLAN)
        self.go(m)
        prompt = m.seen[0][1]["content"]
        self.assertIn("甲-预算.xlsx", prompt)
        self.assertIn("其他文件不要动", prompt)

    def test_a_plan_the_checks_refuse_is_sent_back_once_with_the_reasons(self):
        bad = {"parts": [{"goal": "移动 丙.txt", "writes": [{"op": "move", "src": "丙.txt", "dst": "丙/丙.txt"}]}]}
        m = model(bad, PLAN)
        out, _, _, _ = self.go(m)
        self.assertEqual(out["state"], "completed")
        retry = m.seen[1][-1]["content"]
        self.assertIn("'丙.txt' is not there", retry)

    def test_a_plan_refused_twice_runs_nothing(self):
        bad = {"parts": [{"goal": "移动 丙.txt", "writes": [{"op": "move", "src": "丙.txt", "dst": "丙.txt2"}]}]}
        out, ev, ws, calls = self.go(model(bad, "not json"))
        self.assertEqual(out["state"], "failed")
        self.assertIn("计划没有通过检查", out["report"])
        self.assertEqual(calls, [])
        self.assertFalse(any(e["t"] == "plan_proposed" for e in ev), "an unchecked plan is never shown")

    def test_an_open_goal_asks_first_and_plans_with_the_answer(self):
        m = model({"ask": "按项目还是按文件类型整理？"}, PLAN)
        user = ScriptedUser([{"slot": "rule", "match": "按项目", "reply": "按项目"}])
        out, ev, _, _ = self.go(m, user)
        self.assertEqual(out["state"], "completed")
        self.assertEqual([e["kind"] for e in ev if e["t"] == "ask"], ["clarify", "plan_confirm"])
        self.assertIn("按项目", m.seen[1][1]["content"], "the answer goes into the next prompt")

    def test_a_question_left_unanswered_stops_before_anything_is_done(self):
        m = model(*[{"ask": "按什么整理？"}] * 4)
        out, _, _, calls = self.go(m)
        self.assertEqual(out["state"], "stopped")
        self.assertEqual(calls, [])

    def test_a_declared_source_that_went_missing_is_a_signal(self):
        ws = files_ws("甲-预算.xlsx", "乙-合同.pdf")
        plan = ModelPlanner(model(PLAN)).plan(GOAL, ws=ws)
        (ws / "乙-合同.pdf").rename(ws / "elsewhere.pdf")
        self.assertEqual(missing_files(plan, ws), ["乙-合同.pdf"])

    def test_tree_lists_folders_with_a_slash(self):
        self.assertEqual(tree(files_ws("a/b.txt")), {"a/", "a/b.txt"})


if __name__ == "__main__":
    unittest.main()
