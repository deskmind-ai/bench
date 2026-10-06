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

    def test_a_name_with_a_quote_is_reported_as_missing_intact(self):
        ws = files_ws("Bob's notes.txt")
        plan = ModelPlanner(model({"parts": [{"goal": "移动 Bob's notes.txt", "writes": [
            {"op": "move", "src": "Bob's notes.txt", "dst": "notes.txt"}]}]})).plan(GOAL, ws=ws)
        (ws / "Bob's notes.txt").unlink()
        self.assertEqual(missing_files(plan, ws), ["Bob's notes.txt"])

    def test_the_harness_folder_is_not_listed(self):
        ws = files_ws("a.txt", ".hands/runs/x.json")
        self.assertEqual(tree(ws), {"a.txt"})

    def test_a_later_replan_still_knows_what_the_first_version_finished(self):
        """Review of #13: v2 listed what v1 finished, v3 did not -- done is the orchestrator's whole record."""
        m = model(PLAN, PLAN, PLAN)
        planner = ModelPlanner(m)
        ws = files_ws("甲-预算.xlsx", "乙-合同.pdf")
        v1 = planner.plan(GOAL, ws=ws)
        v2 = planner.replan(GOAL, v1, [], ws=ws, why="file_missing", done=["新建文件夹「甲」"])
        planner.replan(GOAL, v2, [], ws=ws, why="file_missing", done=["新建文件夹「甲」"])
        self.assertIn("新建文件夹「甲」", m.seen[2][1]["content"])

    def test_tree_lists_folders_with_a_slash(self):
        self.assertEqual(tree(files_ws("a/b.txt")), {"a/", "a/b.txt"})


if __name__ == "__main__":
    unittest.main()


class Fixes(unittest.TestCase):
    """T7 dev findings (deskmind#62): a second JSON object, a folder as dst, a copy, small files' contents."""

    def ws(self, *names):
        import tempfile as _t
        ws = Path(_t.mkdtemp(prefix="pm-fix-"))
        for n in names:
            if n.endswith("/"):
                (ws / n).mkdir(parents=True, exist_ok=True)
                continue
            (ws / n).parent.mkdir(parents=True, exist_ok=True)
            (ws / n).write_text(Path(n).name + "\n")
        return ws

    def test_parse_reads_the_first_object_and_ignores_what_follows(self):
        from deskmind_bench.dyn.proto.plan_model import parse
        self.assertEqual(parse('好的：{"ask": "按什么整理？"}\n{"parts": []}'), {"ask": "按什么整理？"})
        with self.assertRaises(ValueError):
            parse("no object")

    def test_a_folder_as_dst_means_into_it(self):
        from deskmind_bench.dyn.proto.plan_model import normalise
        files = {"a.txt", "资料/", "b.txt"}
        got = normalise([{"op": "move", "src": "a.txt", "dst": "资料"}, {"op": "mkdir", "dst": "新"},
                         {"op": "move", "src": "b.txt", "dst": "新/"}, {"op": "move", "src": "x.txt", "dst": "y.txt"}], files)
        self.assertEqual([w["dst"] for w in got], ["资料/a.txt", "新", "新/b.txt", "y.txt"])

    def test_copy_is_checked_and_declared(self):
        from deskmind_bench.dyn.proto.plan_model import dry_run
        files = {"模板/", "模板/t.md"}
        self.assertTrue(dry_run([{"op": "mkdir", "dst": "出"}, {"op": "copy", "src": "模板/t.md", "dst": "出/t.md"},
                                 {"op": "move", "src": "出/t.md", "dst": "出/u.md"}], files).ok)
        self.assertIn("is not there", dry_run([{"op": "copy", "src": "no.md", "dst": "x.md"}], files).problems[0])
        self.assertIn("already exists", dry_run([{"op": "copy", "src": "模板/t.md", "dst": "模板/t.md"}], files).problems[0])

    def test_the_planner_normalises_and_peeks_when_asked(self):
        ws = self.ws("票-1.txt", "资料/")
        (ws / "票-1.txt").write_text("金额：1200 元\n")
        seen = []

        def complete(msgs):
            seen.append(msgs[-1]["content"])
            return json.dumps({"parts": [{"goal": "移动", "writes": [{"op": "move", "src": "票-1.txt", "dst": "资料"}]}]})
        plan = ModelPlanner(complete, peek_bytes=1024).plan("把大额的票放进资料", ws=ws)
        self.assertEqual(plan.subgoals[0].writes[0]["dst"], "资料/票-1.txt")
        self.assertIn("金额：1200 元", seen[0])
        ModelPlanner(complete).plan("把大额的票放进资料", ws=ws)
        self.assertNotIn("金额", seen[1], "no peek unless asked")

    def test_a_declared_copy_is_carried_out_and_recorded(self):
        from deskmind_bench.dyn.graders import write_steps
        from deskmind_bench.dyn.proto.oplist import DeclaredWritesExecutor
        from deskmind_bench.dyn.proto.plan import Subgoal
        import tempfile as _t
        ws = self.ws("模板/t.md")
        run_dir = Path(_t.mkdtemp())
        res = DeclaredWritesExecutor(run_dir).run(Subgoal("s1", "复制模板", writes=[{"op": "mkdir", "dst": "出"},
                                                                                {"op": "copy", "src": "模板/t.md", "dst": "出/t.md"}]),
                                                  ws, 10, None, None)
        self.assertEqual(res.outcome, "met")
        self.assertEqual((ws / "出" / "t.md").read_text(), (ws / "模板" / "t.md").read_text())
        self.assertEqual(len(write_steps(run_dir, [{"t": "subgoal_end", "hands_run": res.hands_run}])), 2)
