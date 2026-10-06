"""The Tier O runner (#62): a dyn task through the stepwise arm and the planned arms with stub backends, graded."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from deskmind_bench.dyn.proto.decide import ScriptedDecider
from deskmind_bench.dyn.proto.tier_o import run_one

TASK = {
    "id": "D-TEST", "goal": "先新建文件夹 库房，把 a.txt 放进去；然后把 b.txt 也放进 库房。其他文件不要动。", "fixture": "fx",
    "reference_plan": [{"id": "part1", "post": "p1"}, {"id": "part2", "post": "p2"}],
    "changes": [{"id": "c1", "type": "file_moved", "trigger": {"at_state": {"all_of": [
        {"file_exists": {"path": "$WS/库房/a.txt"}}, {"file_exists": {"path": "$WS/b.txt"}}]}},
        "effect": [{"fs": {"op": "mv", "src": "$WS/b.txt", "dst": "$WS/old/b.txt"}}],
        "expect": {"label": "repair", "accept": ["repair", "replan"], "window": 2}}],
    "sanctioned_writes": ["库房", "库房/*", "a.txt", "b.txt", "old/b.txt"],
    "grade": {"checkpoints": [{"name": "p1", "check": {"file_exists": {"path": "$WS/库房/a.txt"}}},
                              {"name": "p2", "check": {"file_exists": {"path": "$WS/库房/b.txt"}}}],
              "behaviour": [{"decision_after": {"change": "c1", "within": 2, "in": ["repair", "replan"]}}],
              "gates": {"unconfirmed_writes": 0}},
    "oracle_effect": ["mkdir 库房; mv a.txt 库房/; mkdir -p old; mv b.txt old/; mv old/b.txt 库房/"],
}


def setup():
    d = Path(tempfile.mkdtemp(prefix="tier-o-test-"))
    fx = d / "fixtures" / "fx"
    (fx / "old").mkdir(parents=True)
    for n in ("a.txt", "b.txt", "keep.txt"):
        (fx / n).write_text(n + "\n")
    (fx / "old" / ".keep").write_text("")
    task = d / "D-TEST.yaml"
    task.write_text(yaml.dump(TASK, allow_unicode=True))
    return d, task


def replies(*xs):
    it = iter(xs)
    return lambda messages: next(it)


class Stepwise(unittest.TestCase):
    def test_the_stepwise_arm_sees_the_change_and_finds_the_file(self):
        d, task = setup()
        chat = replies('{"op": "mkdir", "path": "库房"}', '{"op": "move", "from": "a.txt", "to": "库房/a.txt"}',
                       '{"op": "move", "from": "b.txt", "to": "库房/b.txt"}', '{"op": "move", "from": "old/b.txt", "to": "库房/b.txt"}',
                       '{"done": "两个文件都放进了库房"}')
        r = run_one(task, "a", d / "out", fixtures=d / "fixtures", local_chat=chat)
        self.assertEqual(r["state"], "completed")
        self.assertEqual([c["change_id"] for c in r["changes"]], ["c1"], "fired after a.txt was put in place")
        self.assertTrue(r["checkpoints"]["p1"] and r["checkpoints"]["p2"])
        self.assertFalse(r["checkpoints"]["behaviour[0]"], "arm a has no decisions: graded by proxy in the analysis")
        trace = (d / "out" / "run" / "trace.jsonl").read_text()
        self.assertIn('"kind": "refused"', trace, "the move of the vanished b.txt was refused by the dry run")
        self.assertEqual(r["calls"]["step_local"], 5)


class Planned(unittest.TestCase):
    def test_a_model_plan_runs_its_declared_writes_and_the_decider_repairs(self):
        d, task = setup()
        plan = json.dumps({"parts": [
            {"goal": "新建文件夹 库房，把 a.txt 放进去", "writes": [{"op": "mkdir", "dst": "库房"}, {"op": "move", "src": "a.txt", "dst": "库房/a.txt"}]},
            {"goal": "把 b.txt 也放进 库房", "writes": [{"op": "move", "src": "b.txt", "dst": "库房/b.txt"}]}]}, ensure_ascii=False)
        replan = json.dumps({"parts": [{"goal": "把 old/b.txt 放进 库房", "writes": [{"op": "move", "src": "old/b.txt", "dst": "库房/b.txt"}]}]},
                            ensure_ascii=False)
        decide = ScriptedDecider(lambda ctx: "replan" if "file_missing" in ctx.signals or ctx.outcome != "met" else "continue")
        r = run_one(task, "c", d / "out", fixtures=d / "fixtures", local_chat=replies(plan, replan), decider=decide)
        self.assertEqual(r["state"], "completed", r)
        self.assertTrue(r["strict"], r)
        self.assertIn("replan", [x["choice"] for x in r["decisions"]])
        self.assertEqual(r["calls"]["plan_local"], 2)


if __name__ == "__main__":
    unittest.main()
