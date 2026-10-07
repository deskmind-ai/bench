"""T7 amendment 4 (deskmind#62): the numbered answer form for ModelPlanner, and arm (e)'s explicit-choice decider and
pre-plan check. Offline: scripted completions stand in for the model."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from deskmind_bench.dyn.proto.decide import Context                       # noqa: E402
from deskmind_bench.dyn.proto.decide_chat import ChatChoiceDecider, EnoughInfoCheck   # noqa: E402
from deskmind_bench.dyn.proto.events import EventLog, read                  # noqa: E402
from deskmind_bench.dyn.proto.executors import FnExecutor, Result           # noqa: E402
from deskmind_bench.dyn.proto.orchestrator import run                       # noqa: E402
from deskmind_bench.dyn.proto.plan_model import ModelPlanner, PlanFailed, entries, from_numbered   # noqa: E402
from deskmind_bench.dyn.proto.user import ScriptedUser                      # noqa: E402


def files_ws(*names: str) -> Path:
    ws = Path(tempfile.mkdtemp())
    for n in names:
        (ws / n).parent.mkdir(parents=True, exist_ok=True)
        (ws / n).write_text(n)
    return ws


def chat(*replies):
    seen = []

    def complete(messages, temperature=0.0):
        seen.append((messages, temperature))
        r = replies[min(len(seen), len(replies)) - 1]
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
    complete.seen = seen
    return complete


class Numbered(unittest.TestCase):
    def test_numbers_become_paths_built_by_code(self):
        listing = ["backup/", "backup/记录-30.txt", "draft-21.csv", "todo-94.txt"]
        writes, problems = from_numbered([
            {"op": "mkdir", "to": "资料"},
            {"op": "move", "file": 3, "to": "资料"},
            {"op": "move", "file": 4, "to": "", "rename": "会议纪要-2.txt"},
            {"op": "move", "file": 2, "to": ""},
            {"op": "copy", "file": 3, "to": "备份", "rename": "draft-copy.csv"},
            {"op": "delete", "file": 4}], listing)
        self.assertEqual(problems, [])
        self.assertEqual(writes, [
            {"op": "mkdir", "dst": "资料"},
            {"op": "move", "src": "draft-21.csv", "dst": "资料/draft-21.csv"},
            {"op": "move", "src": "todo-94.txt", "dst": "会议纪要-2.txt"},
            {"op": "move", "src": "backup/记录-30.txt", "dst": "记录-30.txt"},
            {"op": "copy", "src": "draft-21.csv", "dst": "备份/draft-copy.csv"},
            {"op": "delete", "src": "todo-94.txt"}])

    def test_a_bad_number_or_name_is_a_problem_for_the_model(self):
        _, problems = from_numbered([{"op": "move", "file": 9, "to": "x"}, {"op": "move", "file": "a"},
                                     {"op": "move", "file": 1, "to": "x", "rename": "a/b"}], ["a.txt"])
        self.assertEqual(len(problems), 3)

    def test_the_planner_shows_numbers_and_sends_a_bad_one_back(self):
        ws = files_ws("draft-21.csv", "todo-94.txt")
        m = chat({"parts": [{"goal": "移动", "writes": [{"op": "move", "file": 7, "to": "资料"}]}]},
                 {"parts": [{"goal": "移动", "writes": [{"op": "mkdir", "to": "资料"},
                                                         {"op": "move", "file": 1, "to": "资料"}]}]})
        plan = ModelPlanner(lambda msgs: m(msgs), form="numbered").plan("把 draft 放进资料", ws=ws)
        self.assertIn("1. draft-21.csv", m.seen[0][0][1]["content"])
        self.assertTrue(any("there is no file 7" in x["content"] for x in m.seen[1][0] if x["role"] == "user"))
        self.assertEqual(plan.writes()[-1]["dst"], "资料/draft-21.csv")
        self.assertEqual(entries(ws), ["draft-21.csv", "todo-94.txt"])

    def test_paths_stay_the_default(self):
        ws = files_ws("a.txt")
        m = chat({"parts": [{"goal": "改名", "writes": [{"op": "move", "src": "a.txt", "dst": "b.txt"}]}]})
        plan = ModelPlanner(lambda msgs: m(msgs)).plan("改名", ws=ws)
        self.assertEqual(plan.writes()[0]["dst"], "b.txt")
        with self.assertRaises(ValueError):
            ModelPlanner(lambda msgs: "", form="letters")


class ArmE(unittest.TestCase):
    def ctx(self, **kw):
        base = dict(goal="整理", plan_version=1, parts=[{"id": "s1", "goal": "a", "status": "now"}], outcome="unmet",
                    detail="", signals=["file_missing"], said=[], can_repair=True, can_replan=True, can_ask=True,
                    can_handoff=False)
        base.update(kw)
        return Context(**base)

    def test_the_greedy_letter_decides_and_agreement_is_the_confidence(self):
        ctx = self.ctx()   # options in order: continue, repair, replan, ask, stop
        d = ChatChoiceDecider(chat("D", "D", "C", "D", "D"))
        choice, probs, by = d.decide(ctx)
        self.assertEqual(choice, "ask")
        self.assertEqual(probs["ask"], 0.8)
        self.assertEqual(probs["replan"], 0.2)
        self.assertEqual(by, "local-4b")

    def test_no_letter_is_an_error_never_continue(self):
        with self.assertRaises(ValueError):
            ChatChoiceDecider(chat("嗯", "好", "?", "…", "x")).decide(self.ctx())

    def test_a_not_started_part_reads_as_such(self):
        d = ChatChoiceDecider(chat("A"), samples=0)
        msgs = d.prompt(self.ctx(outcome="not_started", said=["第三件不用做了"]), ["continue", "stop"])
        self.assertIn("还没开始", msgs[0]["content"])
        self.assertIn("第三件不用做了", msgs[0]["content"])

    def test_the_precheck_says_ask_when_the_answer_is_B(self):
        check = EnoughInfoCheck(chat("B", "B", "A", "B", "B"))
        self.assertFalse(check("整理一下", ["a.txt"], []))
        self.assertEqual(check.p_ask, 0.8)
        self.assertTrue(EnoughInfoCheck(chat("A"), samples=0)("按类型整理", ["a.txt"], []))

    def test_an_open_goal_asks_first_then_plans_with_the_answer(self):
        ws = files_ws("a.csv", "b.md")
        answers = iter([False, True])
        planner_model = chat({"ask": "按什么整理？"},
                             {"parts": [{"goal": "分开放", "writes": [{"op": "mkdir", "to": "表格"},
                                                                       {"op": "move", "file": 1, "to": "表格"}]}]})
        planner = ModelPlanner(lambda msgs: planner_model(msgs), form="numbered",
                               precheck=lambda goal, listing, said: next(answers))
        log_path = Path(tempfile.mkdtemp()) / "orchestrator.jsonl"

        def do(sg, ws, max_actions):
            for w in sg.writes or []:
                if w["op"] == "mkdir":
                    (ws / w["dst"]).mkdir()
                elif w["op"] == "move":
                    (ws / w["src"]).rename(ws / w["dst"])
            return Result("met", steps=len(sg.writes or []))
        out = run("整理一下这个文件夹", ws, planner=planner, decider=ChatChoiceDecider(chat("A")),
                  executor=FnExecutor(do), user=ScriptedUser([{"slot": "rule", "match": "整理", "reply": "csv 放表格"}]),
                  log=EventLog(log_path, "t1"))
        ev = read(log_path)
        self.assertEqual(out["state"], "completed", out)
        self.assertEqual([e["kind"] for e in ev if e["t"] == "ask"][0], "clarify")
        self.assertTrue((ws / "表格" / "a.csv").exists())


if __name__ == "__main__":
    unittest.main()


class DevFindings(unittest.TestCase):
    """T7 dev, numbered form (10-07): the 4B writes 'mv' / 'rename' / 'cp', and the precheck looped after an answer."""

    def test_shell_style_op_names_are_read(self):
        listing = ["a.txt", "b.txt", "资料/", "资料/c.txt"]
        out, problems = from_numbered([{"op": "mv", "file": 1, "to": "资料"}, {"op": "rename", "file": 2, "rename": "b2.txt"},
                                       {"op": "rename", "file": 4, "rename": "d.txt"}, {"op": "cp", "file": 1, "to": "资料", "rename": "e.txt"}],
                                      listing)
        self.assertEqual(problems, [])
        self.assertEqual([(w["op"], w["src"], w["dst"]) for w in out],
                         [("move", "a.txt", "资料/a.txt"), ("move", "b.txt", "b2.txt"), ("move", "资料/c.txt", "资料/d.txt"),
                          ("copy", "a.txt", "资料/e.txt")])

    def test_the_precheck_is_asked_once(self):
        ws = files_ws("a.txt")
        asked = []

        class No:
            def __call__(self, goal, listing, said):
                asked.append(list(said))
                return False
        planner = ModelPlanner(chat({"ask": "按什么整理？"}, {"parts": [{"goal": "移动", "writes": []}]}),
                               form="numbered", precheck=No())
        first = planner.plan("整理一下", ws=ws)
        self.assertTrue(first.question)
        second = planner.plan("整理一下", ws=ws, said=["按类型"])
        self.assertIsNone(second.question)
        self.assertEqual(asked, [[]], "not asked again once the user has answered")
