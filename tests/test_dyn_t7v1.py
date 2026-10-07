"""T7 v1 (deskmind#62): the fixed planner, the start gate, the reworded-part executor and the ceiling decider."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deskmind_bench.dyn.proto.decide import Context, ScriptedDecider
from deskmind_bench.dyn.proto.events import EventLog
from deskmind_bench.dyn.proto.plan import Subgoal
from deskmind_bench.dyn.proto.t7v1 import FixedPlanner, OracleDecider, Reworded, start_gate
from deskmind_bench.dyn.proto.user import ScriptedUser

PARTS = [{"goal": "新建 资料，放 a", "writes": [{"op": "mkdir", "dst": "资料"}, {"op": "move", "src": "a.txt", "dst": "资料/a.txt"}]}]
AFTER = [{"goal": "新建 归档，放 a", "writes": [{"op": "mkdir", "dst": "归档"}, {"op": "move", "src": "a.txt", "dst": "归档/a.txt"}]}]


class NoHooks:
    def at_start(self): ...
    def on_ask(self, kind, text): ...


def ctx_opts(ctx):
    return ctx.options()


class Fixed(unittest.TestCase):
    def test_the_fixed_plan_and_the_after_answer_plan(self):
        fp = FixedPlanner(PARTS, AFTER, replanner=None)
        p = fp.plan("g")
        self.assertEqual([w["dst"] for w in p.subgoals[0].writes], ["资料", "资料/a.txt"])
        self.assertEqual(p.writes()[1]["src"], "a.txt")
        fp.said_before = ["放归档"]
        self.assertEqual(fp.plan("g").subgoals[0].writes[0]["dst"], "归档")

    def test_a_frozen_plan_that_asks_first(self):
        fp = FixedPlanner(AFTER, AFTER, replanner=None, question="放哪？")
        self.assertEqual(fp.plan("g").question, "放哪？")
        self.assertIsNone(fp.plan("g", said=["归档"]).question)


class Gate(unittest.TestCase):
    def go(self, choice):
        d = Path(tempfile.mkdtemp())
        log = EventLog(d / "orchestrator.jsonl", "t")
        fp = FixedPlanner(PARTS, AFTER, replanner=None)
        user = ScriptedUser([{"slot": "s0", "match": "哪个|怎么", "reply": "放归档"}])
        out = start_gate(ScriptedDecider(lambda ctx: choice, by="code"), fp, "g", d, user, log, NoHooks(), turns=3)
        events = [json.loads(l) for l in (d / "orchestrator.jsonl").read_text().splitlines()]
        return out, fp, events

    def test_ask_at_the_gate_uses_the_answer(self):
        out, fp, events = self.go("ask")
        self.assertIsNone(out)
        self.assertEqual([e["t"] for e in events], ["decision", "ask", "user_msg"])
        self.assertEqual(fp.plan("g").subgoals[0].writes[0]["dst"], "归档")

    def test_stop_at_the_gate_ends_the_run(self):
        out, _, events = self.go("stop")
        self.assertEqual(out, "stop")
        self.assertEqual(events[-1]["t"], "done")

    def test_continue_at_the_gate_keeps_the_plan(self):
        out, fp, events = self.go("continue")
        self.assertIsNone(out)
        self.assertEqual(fp.plan("g").subgoals[0].writes[0]["dst"], "资料")


class Oracle(unittest.TestCase):
    def test_the_ceiling_reacts_once_to_a_fired_change(self):
        from types import SimpleNamespace
        d = Path(tempfile.mkdtemp())
        task = SimpleNamespace(changes=[SimpleNamespace(id="c1", expect={"label": "repair", "accept": ["repair", "replan"]})])
        o = OracleDecider(task, d)
        ctx = lambda rep: Context(goal="g", plan_version=1, parts=[], outcome="met", detail="", signals=[], said=[],  # noqa: E731
                                  can_repair=rep, can_replan=True, can_ask=True, can_handoff=False)
        self.assertEqual(o.decide(ctx(True))[0], "continue", "nothing fired yet")
        (d / "changes.jsonl").write_text(json.dumps({"change_id": "c1"}) + "\n")
        self.assertEqual(o.decide(ctx(False))[0], "replan", "repair not offered: the next accepted reaction")
        self.assertEqual(o.decide(ctx(True))[0], "continue", "once per change")


class Words(unittest.TestCase):
    def test_a_reworded_part_goes_to_the_reworded_executor(self):
        calls = []

        class E:
            def __init__(self, tag):
                self.tag = tag

            def run(self, sg, *a, **k):
                calls.append((self.tag, sg.writes is None))
        r = Reworded(E("declared"), E("reworded"))
        sg = Subgoal("s1", "放 a", "oplist", None, "放 a", writes=[{"op": "mkdir", "dst": "x"}])
        r.run(sg, None, 5, None, None)
        sg.goal += "（用户说：放归档）"
        r.run(sg, None, 5, None, None)
        self.assertEqual(calls, [("declared", False), ("reworded", True)])


if __name__ == "__main__":
    unittest.main()
