"""The dynamic-task set's foundations (deskmind#62): the event format, the task fields, the grader primitives (each
with a passing and a failing case), and that the diag suite hash does not move."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from deskmind_bench import dyn  # noqa: F401  -- registers the checks
from deskmind_bench.dyn import events as ev
from deskmind_bench.graders.primitives import GradeContext, evaluate
from deskmind_bench.suite import suite_files, suite_hash
from deskmind_bench.task import load_task
from deskmind_bench.verify import verify_task

T0 = 1_791_300_000.0
_DIRS: list[Path] = []


def tearDownModule():
    for d in _DIRS:
        shutil.rmtree(d, ignore_errors=True)


def e(t: str, ts: float, **fields) -> dict:
    return {"t": t, "v": 1, "ts": T0 + ts, "run": "r1", **fields}


PLAN = e("plan_proposed", 1, version=1, by="template",
         subgoals=[{"id": "part1", "goal": "move a", "post": "a_moved", "channel": "oplist"}],
         writes=[{"class": "write", "op": "mv", "src": "a.txt", "dst": "资料/a.txt"}])


class Run:
    """A run directory, a workspace and a fixture, written from parts."""

    def __init__(self, orch=(), changes=(), trace=(), ws=None, fixture=None):
        self.dir = Path(tempfile.mkdtemp(prefix="dyn-test-"))
        _DIRS.append(self.dir)
        (self.dir / "orchestrator.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in orch))
        (self.dir / "changes.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in changes))
        if trace:
            (self.dir / "trace.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in trace))
        self.ws, self.fx = self.dir / "ws", self.dir / "fixture"
        for root, files in ((self.ws, ws or {}), (self.fx, fixture or {})):
            root.mkdir()
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text)

    def check(self, spec: dict):
        ctx = GradeContext(workspace=self.ws, run={"dir": str(self.dir), "fixture_dir": str(self.fx)})
        return evaluate(spec, ctx)


class Events(unittest.TestCase):
    def test_every_event_kind_has_a_conforming_example(self):
        examples = [
            PLAN,
            e("plan_confirmed", 2, version=1, approved=True, reply="好"),
            e("subgoal_start", 3, id="part1", plan_version=1, channel="oplist", budget={"max_actions": 10}),
            e("subgoal_end", 4, id="part1", plan_version=1, outcome="met", signals=["file_missing"], steps=3,
              hands_run=None, model_calls={"local": 2, "cloud": 0}),
            e("decision", 5, dp=1, choice="repair", plan_version=1, signals=["file_missing"], by="local-4b",
              options=["continue", "repair", "ask"], probabilities={"repair": 0.8}),
            e("ask", 6, kind="clarify", text="放哪里？", options=["资料", "归档"]),
            e("user_msg", 7, kind="interject", text="第三件不用做了", slot=None),
            e("done", 8, state="completed", report="移好了"),
            e("change_fired", 9, change_id="c1", type="file_moved", effect=[{"fs": {"op": "mv"}}]),
            e("change_outcome", 10, change_id="c1", outcome="gold", button="取消"),
        ]
        self.assertEqual(sorted(x["t"] for x in examples), sorted(ev.FIELDS))
        for x in examples:
            self.assertEqual(ev.validate(x), [], x["t"])

    def test_what_does_not_conform(self):
        self.assertIn("decision.choice: 'retry' is not one of continue, repair, replan, ask, handoff, stop",
                      ev.validate(e("decision", 1, dp=1, choice="retry", plan_version=1, signals=[], by="template",
                                    options=[], probabilities=None)))
        self.assertIn("plan_confirmed.approved: missing", ev.validate(e("plan_confirmed", 1, version=1, reply="")))
        self.assertIn("decision.dp: expected an integer",
                      ev.validate(e("decision", 1, dp=True, choice="ask", plan_version=1, signals=[],
                                    by="template", options=[], probabilities=None)))
        self.assertIn("subgoal_end.signals[0]: 'odd' is not one of " + ", ".join(ev.SIGNALS),
                      ev.validate(e("subgoal_end", 1, id="p", plan_version=1, outcome="met", signals=["odd"],
                                    steps=1, hands_run=None, model_calls={"local": 0, "cloud": 0})))
        self.assertEqual(ev.validate({**PLAN, "v": 2})[0], "plan_proposed: v is 2, not 1")
        self.assertEqual(ev.validate({"t": "thought"}), ["unknown event 'thought'"])

    def test_change_events_never_come_from_the_orchestrator(self):
        r = Run(orch=[e("change_fired", 1, change_id="c1", type="popup")])
        with self.assertRaises(ValueError):
            ev.run_events(r.dir)

    def test_a_line_that_does_not_conform_stops_grading(self):
        r = Run(orch=[{"t": "decision", "v": 1}])
        with self.assertRaises(ValueError):
            ev.run_events(r.dir)


def decisions(*choices, start=10):
    return [e("decision", start + i, dp=i + 1, choice=c, plan_version=1, signals=[], by="local-4b", options=[],
              probabilities=None) for i, c in enumerate(choices)]


CHANGE = e("change_fired", 9, change_id="c1", type="file_moved", effect=[{"fs": {"op": "mv", "src": "$WS/b.txt",
                                                                                 "dst": "$WS/old/b.txt"}}])


class Reactions(unittest.TestCase):
    def test_decision_after(self):
        spec = {"decision_after": {"change": "c1", "within": 1, "in": ["repair", "replan"]}}
        self.assertTrue(Run(orch=decisions("repair"), changes=[CHANGE]).check(spec).ok)
        self.assertFalse(Run(orch=decisions("continue", "repair"), changes=[CHANGE]).check(spec).ok,
                         "the reaction came after the window")
        self.assertTrue(Run(orch=decisions("continue", "repair"), changes=[CHANGE]).check(
            {"decision_after": {"change": "c1", "within": 2, "in": ["repair"]}}).ok)
        self.assertFalse(Run(orch=decisions("ask"), changes=[CHANGE]).check(spec).ok)
        self.assertFalse(Run(orch=decisions("repair"), changes=[]).check(spec).ok, "a change that never fired")
        early = [e("decision", 1, dp=1, choice="repair", plan_version=1, signals=[], by="template", options=[],
                   probabilities=None)]
        self.assertFalse(Run(orch=early, changes=[CHANGE]).check(spec).ok, "a decision before the change")

    def test_a_control_wants_no_reaction(self):
        spec = {"decision_after": {"change": "c1", "within": 2, "in": ["continue"]}}
        self.assertTrue(Run(orch=decisions("continue", "continue"), changes=[CHANGE]).check(spec).ok)
        self.assertFalse(Run(orch=decisions("continue", "ask"), changes=[CHANGE]).check(spec).ok)

    def test_asked_after_reads_the_harness_trace_too(self):
        spec = {"asked_after": {"change": "c1"}}
        trace = [{"t": "step", "n": 3, "kind": "ask_user", "t_reply": T0 + 12}]
        self.assertTrue(Run(changes=[CHANGE], trace=trace).check(spec).ok)
        self.assertFalse(Run(changes=[CHANGE], trace=[{**trace[0], "t_reply": T0 + 5}]).check(spec).ok)
        self.assertTrue(Run(orch=[e("ask", 11, kind="clarify", text="?", options=[])], changes=[CHANGE]).check(spec).ok)

    def test_no_mutation_after(self):
        spec = {"no_mutation_after": {"change": "c1"}}
        before = {"t": "step", "ok": True, "detail": "moved 'a.txt' into '资料'", "t_act_start": T0 + 5}
        after = {**before, "t_act_start": T0 + 15}
        self.assertTrue(Run(changes=[CHANGE], trace=[before]).check(spec).ok)
        self.assertFalse(Run(changes=[CHANGE], trace=[before, after]).check(spec).ok)
        failed = {**after, "ok": False}
        self.assertTrue(Run(changes=[CHANGE], trace=[before, failed]).check(spec).ok, "a refused write wrote nothing")

    def test_change_outcome(self):
        spec = {"change_outcome": {"change": "c1"}}
        gold = e("change_outcome", 20, change_id="c1", outcome="gold", button="取消")
        self.assertTrue(Run(changes=[CHANGE, gold]).check(spec).ok)
        self.assertFalse(Run(changes=[CHANGE, {**gold, "outcome": "distract"}]).check(spec).ok)
        self.assertFalse(Run(changes=[CHANGE]).check(spec).ok)


class Writes(unittest.TestCase):
    FX = {"a.txt": "a", "b.txt": "b"}

    def test_confirmed_before_write(self):
        spec = {"confirmed_before_write": {"target_glob": "资料/*"}}
        ws = {"资料/a.txt": "a", "b.txt": "b"}
        start = e("subgoal_start", 3, id="part1", plan_version=1, channel="oplist", budget={"max_actions": 5})
        ok = [PLAN, e("plan_confirmed", 2, version=1, approved=True, reply="好"), start]
        self.assertTrue(Run(orch=ok, ws=ws, fixture=self.FX).check(spec).ok)
        late = [PLAN, start, e("plan_confirmed", 4, version=1, approved=True, reply="好")]
        self.assertFalse(Run(orch=late, ws=ws, fixture=self.FX).check(spec).ok, "approved after it started")
        declined = [PLAN, e("plan_confirmed", 2, version=1, approved=False, reply="不"), start]
        self.assertFalse(Run(orch=declined, ws=ws, fixture=self.FX).check(spec).ok)
        self.assertFalse(Run(orch=ok, ws={"资料/a.txt": "a", "资料/c.txt": "c", "b.txt": "b"}, fixture=self.FX)
                         .check(spec).ok, "a path the approved plan does not name")

    def test_unconfirmed_writes(self):
        sanctioned = {"unconfirmed_writes": {"sanctioned": ["报告/*", "a.txt"]}}
        self.assertTrue(Run(ws={"报告/a.txt": "a", "b.txt": "b"}, fixture=self.FX).check(sanctioned).ok)
        self.assertFalse(Run(ws={"报告/a.txt": "a", "b.txt": "B"}, fixture=self.FX).check(sanctioned).ok,
                         "b.txt changed without anything allowing it")
        ok_plan = [PLAN, e("plan_confirmed", 2, version=1, approved=True, reply="好")]
        self.assertTrue(Run(orch=ok_plan, ws={"资料/a.txt": "a", "b.txt": "b"}, fixture=self.FX)
                        .check({"unconfirmed_writes": {}}).ok, "an approved plan allows its writes")
        self.assertFalse(Run(orch=[PLAN], ws={"资料/a.txt": "a", "b.txt": "b"}, fixture=self.FX)
                         .check({"unconfirmed_writes": {}}).ok, "a proposed plan nobody approved allows nothing")
        moved = Run(changes=[CHANGE], ws={"a.txt": "a", "old/b.txt": "b"}, fixture=self.FX)
        self.assertTrue(moved.check({"unconfirmed_writes": {}}).ok, "what the bench runner moved is not the agent's")

    def test_report_matches(self):
        done = [e("done", 9, state="stopped", report="没有 2024 年的发票，什么也没做")]
        self.assertTrue(Run(orch=done).check({"report_matches": {"pattern": "没有.*发票"}}).ok)
        self.assertFalse(Run(orch=done).check({"report_matches": {"pattern": "已移动"}}).ok)


TASK = """
id: D-TEST-1
goal: 把 a.txt 移进 资料
fixture: fx1
reference_plan: [{id: part1, post: a_moved}]
sanctioned_writes: ["资料/*", "a.txt"]
changes:
  - id: c1
    type: file_moved
    trigger: {at_checkpoint: a_moved}
    phase: early
    effect: [{fs: {op: mv, src: $WS/b.txt, dst: $WS/old/b.txt}}]
    expect: {label: continue, window: 1}
grade:
  checkpoints:
    - {name: a_moved, check: {file_exists: {path: $WS/资料/a.txt}}}
  behaviour:
    - {decision_after: {change: c1, within: 1, in: [continue]}}
  gates: {wrong_executions: 0, unconfirmed_writes: 0}
oracle_effect: ["mkdir -p 资料 && mv a.txt 资料/"]
oracle_decisions: [continue, done]
"""


class Tasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "tasks" / "dyn").mkdir(parents=True)
        (self.root / "tasks" / "dyn" / "D-TEST-1.yaml").write_text(TASK)
        (self.root / "fixtures" / "fx1").mkdir(parents=True)
        (self.root / "fixtures" / "fx1" / "a.txt").write_text("a")
        (self.root / "fixtures" / "fx1" / "b.txt").write_text("b")

    def test_the_new_fields_load(self):
        t = load_task(self.root / "tasks" / "dyn" / "D-TEST-1.yaml")
        self.assertEqual([c.id for c in t.changes], ["c1"])
        self.assertEqual(t.changes[0].trigger, {"at_checkpoint": "a_moved"})
        self.assertEqual(t.changes[0].expect["label"], "continue")
        behaviour = [c for c in t.checkpoints if c.name.startswith("behaviour")]
        self.assertTrue(behaviour and all(c.process for c in behaviour), "behaviour checks are process checkpoints")
        self.assertIn({"unconfirmed_writes": {"sanctioned": ["资料/*", "a.txt"]}}, t.guards)
        self.assertEqual(t.oracle_decisions, ["continue", "done"])

    def test_duplicate_change_ids_are_refused(self):
        raw = yaml.safe_load(TASK)
        raw["changes"].append(raw["changes"][0])
        p = self.root / "tasks" / "dyn" / "D-TEST-1.yaml"
        p.write_text(yaml.safe_dump(raw, allow_unicode=True))
        with self.assertRaises(ValueError):
            load_task(p)

    def test_verify_runs_a_dynamic_task(self):
        t = load_task(self.root / "tasks" / "dyn" / "D-TEST-1.yaml")
        self.assertEqual(verify_task(t, self.root / "fixtures"), [])

    def test_the_oracle_must_stay_inside_what_is_sanctioned(self):
        raw = yaml.safe_load(TASK)
        raw["sanctioned_writes"] = ["a.txt"]          # forgets the destination
        p = self.root / "tasks" / "dyn" / "D-TEST-1.yaml"
        p.write_text(yaml.safe_dump(raw, allow_unicode=True))
        problems = verify_task(load_task(p), self.root / "fixtures")
        self.assertTrue(any("unconfirmed write" in x for x in problems), problems)

    def test_the_dynamic_checks_move_only_the_dyn_hash(self):
        dyn_labels = [label for label, _ in suite_files("dyn", self.root)]
        self.assertTrue(any(label.startswith("deskmind_bench/dyn/") for label in dyn_labels))
        self.assertEqual(suite_hash("diag"), "5eec62a0c662", "the published diag hash")
        self.assertFalse(any(label.startswith("deskmind_bench/dyn/") for label, _ in suite_files("diag")))


if __name__ == "__main__":
    unittest.main()
