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
from deskmind_bench.dyn.proto.orchestrator import Budget, NoHooks, run # noqa: E402
from deskmind_bench.dyn.proto.plan import Subgoal, TemplatePlanner, clause_writes   # noqa: E402
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
        self.assertEqual([(w["op"], w["src"], w["dst"]) for w in plan.writes()],
                         [("mkdir", None, "资料"), ("move", "draft-21.csv", "资料/draft-21.csv"),
                          ("rename", "todo-94.txt", "会议纪要-2.txt"), ("move", "backup/记录-30.txt", "记录-30.txt")])

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
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt", "清单-87.log")
        queue = Path(tempfile.mkdtemp()) / "user_queue.jsonl"
        add = {1: lambda ws: queue.write_text(json.dumps({"text": "再把 清单-87.log 删除"}, ensure_ascii=False) + "\n")}

        class Adds(TemplatePlanner):      # a planner that reads the amendment (the cloud planner's job in arm d)
            def replan(self, goal, plan, said):
                new = super().replan(goal, plan, said)
                new.subgoals.append(Subgoal(f"v{new.version}x", "把 清单-87.log 删除"))
                return new
        decide = lambda ctx: "replan" if "user_interjected" in ctx.signals else "continue"
        log_path = Path(tempfile.mkdtemp()) / "orchestrator.jsonl"
        run(GOAL, ws, planner=Adds(), decider=ScriptedDecider(decide), executor=FnExecutor(executor(add)),
            user=ScriptedUser(queue=queue), log=EventLog(log_path, "t1"))
        ev = read(log_path)
        self.assertEqual([e["version"] for e in ev if e["t"] == "plan_proposed"], [1, 2])
        self.assertEqual([c["version"] for c in ev if c["t"] == "plan_confirmed"], [1, 2], "the new delete is shown")
        self.assertIn("delete", next(e for e in ev if e["t"] == "ask" and "第 2 版" in e["text"])["text"])

    def test_the_template_planner_does_not_turn_what_the_user_said_into_parts(self):
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        queue = Path(tempfile.mkdtemp()) / "q.jsonl"
        say = {1: lambda ws: queue.write_text(json.dumps({"text": "慢一点"}, ensure_ascii=False) + "\n")}
        fn = executor(say)
        decide = lambda ctx: "replan" if "user_interjected" in ctx.signals else "continue"
        _, ev = self.go(ws, fn, decide, ScriptedUser(queue=queue))
        self.assertNotIn("慢一点", " ".join(fn.calls))
        v2 = [e for e in ev if e["t"] == "plan_proposed"][1]
        self.assertEqual(len(v2["subgoals"]), 2, "the two parts left, nothing added")

    def test_a_part_met_after_a_repair_is_not_run_again_after_a_replan(self):
        ws = files_ws("todo-94.txt", "backup/记录-30.txt")
        queue = Path(tempfile.mkdtemp()) / "q.jsonl"
        heal = {1: lambda ws: (ws / "draft-21.csv").write_text("x"),
                2: lambda ws: queue.write_text(json.dumps({"text": "顺便看一下"}, ensure_ascii=False) + "\n")}
        fn = executor(heal)
        decide = lambda ctx: ("repair" if ctx.can_repair else
                              "replan" if "user_interjected" in ctx.signals and ctx.can_replan else "continue")
        _, ev = self.go(ws, fn, decide)
        self.assertEqual(sum("draft-21.csv" in c for c in fn.calls), 2, "failed once, repaired once, never again")

    def test_skipping_an_unmet_part_ends_failed_and_names_it(self):
        ws = files_ws("todo-94.txt", "backup/记录-30.txt")      # part 1 cannot be met
        out, _ = self.go(ws, executor(), lambda ctx: "continue")
        self.assertEqual(out["state"], "failed")
        self.assertIn("draft-21.csv", out["report"])

    def test_a_clean_run_passes_the_write_gates(self):
        """Graded with the dyn graders (#7): what the user confirmed is what the parts write."""
        import shutil
        from deskmind_bench.dyn import graders  # noqa: F401  (registers the predicates)
        from deskmind_bench.graders.primitives import GradeContext, evaluate
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt", "other.txt")
        fixture = Path(tempfile.mkdtemp()) / "fx"
        shutil.copytree(ws, fixture)

        def do(sg, ws, max_actions):
            for w in clause_writes(sg.clause):
                if w["op"] == "mkdir":
                    (ws / w["dst"]).mkdir(parents=True, exist_ok=True)
                else:
                    (ws / w["dst"]).parent.mkdir(parents=True, exist_ok=True)
                    (ws / w["src"]).rename(ws / w["dst"])
            return Result("met", steps=2)
        run_dir = Path(tempfile.mkdtemp())
        out = run(GOAL, ws, planner=TemplatePlanner(), decider=ScriptedDecider(lambda c: "continue"),
                  executor=FnExecutor(do), user=ScriptedUser(), log=EventLog(run_dir / "orchestrator.jsonl", "t1"))
        self.assertEqual(out["state"], "completed")
        ctx = GradeContext(workspace=ws, run={"dir": str(run_dir), "fixture_dir": str(fixture)})
        for spec in ({"unconfirmed_writes": {}}, {"confirmed_before_write": {"target_glob": "*"}},
                     {"confirmed_before_write": {"target_glob": "资料/*"}}):
            c = evaluate(spec, ctx)
            self.assertTrue(c.ok, f"{spec}: {c}")

    def test_where_expected_matches_folders_as_words(self):
        ws = files_ws("a/x.txt", "backup/y.txt")
        self.assertFalse(where_expected("把 x.txt 放到桌面", "x.txt", ws), "a folder named 'a' is not named here")
        self.assertTrue(where_expected("把 backup 里的 y.txt 移到顶层", "y.txt", ws))

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


class Decider(unittest.TestCase):
    def test_a_reply_without_probabilities_never_defaults_to_continue(self):
        import io, json as _j
        from unittest import mock
        from deskmind_bench.dyn.proto.decide import Context, SystemOneDecider
        ctx = Context(goal="g", plan_version=1, parts=[], outcome="unmet", detail="", signals=["file_missing"], said=[],
                      can_repair=True, can_replan=True, can_ask=True, can_handoff=False)

        def reply(answer):
            r = io.BytesIO(_j.dumps({"answers": {"next": answer}}).encode())
            r.__enter__ = lambda *a: r
            r.__exit__ = lambda *a: False
            return r
        d = SystemOneDecider("http://x")
        with mock.patch("urllib.request.urlopen", return_value=reply({"type": "choice", "choice": "ask"})):
            self.assertEqual(d.decide(ctx)[0], "ask")
        with mock.patch("urllib.request.urlopen", return_value=reply({"type": "choice"})):
            with self.assertRaises(ValueError):
                d.decide(ctx)


if __name__ == "__main__":
    unittest.main()


class Runner(unittest.TestCase):
    """The bench runner fires a dyn task's changes at the orchestrator's hook points (proto/runner.py)."""

    def task(self, changes, checkpoints=()):
        from types import SimpleNamespace
        from deskmind_bench.task import Change
        return SimpleNamespace(
            app="com.apple.finder", reset_apps=[], vars={}, checkpoints=list(checkpoints),
            reference_plan=[{"id": "part1"}, {"id": "part2"}, {"id": "part3"}],
            changes=[Change(id=c["id"], type=c["type"], trigger=c["trigger"], effect=c["effect"]) for c in changes])

    def go(self, task, ws, decide, fn=None):
        from deskmind_bench.dyn.proto.runner import ChangeHooks
        run_dir = self.last_run_dir = Path(tempfile.mkdtemp())
        hooks = ChangeHooks(task, ws, run_dir, "t1")
        fn = fn or executor()
        out = run(GOAL, ws, planner=TemplatePlanner(), decider=ScriptedDecider(decide), executor=FnExecutor(fn),
                  user=ScriptedUser(queue=run_dir / "user_queue.jsonl"), log=EventLog(run_dir / "orchestrator.jsonl", "t1"),
                  hooks=hooks)
        return out, read(run_dir / "orchestrator.jsonl"), read(run_dir / "changes.jsonl"), fn

    def test_before_subgoal_fires_before_that_part_runs(self):
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        t = self.task([{"id": "c1", "type": "file_moved", "trigger": {"before_subgoal": "part2"},
                        "effect": [{"fs": {"op": "mv", "src": "$WS/todo-94.txt", "dst": "$WS/old/todo-94.txt"}}]}])
        seen = []
        _, ev, ch, _ = self.go(t, ws, lambda ctx: seen.append((ctx.outcome, ctx.signals)) or "stop")
        self.assertEqual([c["change_id"] for c in ch if c["t"] == "change_fired"], ["c1"])
        self.assertEqual(seen[0][0], "unmet", "part 2 ran after its file was moved")
        self.assertIn("file_missing", seen[0][1])

    def test_on_ask_user_says_reaches_the_orchestrator_as_an_interjection(self):
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        t = self.task([{"id": "c2", "type": "user_amend", "trigger": {"on_ask": {"kind": "plan_confirm"}},
                        "effect": [{"user_says": "第三件不用做了"}]}])
        decide = lambda ctx: "stop" if "user_interjected" in ctx.signals else "continue"
        out, ev, ch, _ = self.go(t, ws, decide)
        self.assertIn({"t": "user_msg", "kind": "interject", "text": "第三件不用做了"},
                      [{k: e[k] for k in ("t", "kind", "text")} for e in ev if e["t"] == "user_msg"])
        self.assertEqual(out["state"], "stopped")

    def test_hooks_are_closed_however_the_run_ends(self):
        """A run that dies mid-way still closes its hooks: a dialog a change put up must not stay on the screen."""
        closed = []

        class Hooks(NoHooks):
            def close(self):
                closed.append(True)

        def boom(sg, ws, max_actions):
            raise KeyboardInterrupt
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        run_dir = Path(tempfile.mkdtemp())
        with self.assertRaises(KeyboardInterrupt):
            run(GOAL, ws, planner=TemplatePlanner(), decider=ScriptedDecider(lambda ctx: "stop"),
                executor=FnExecutor(boom), user=ScriptedUser(queue=run_dir / "user_queue.jsonl"),
                log=EventLog(run_dir / "orchestrator.jsonl", "t1"), hooks=Hooks())
        self.assertEqual(closed, [True])

    def test_each_part_started_is_logged_with_the_reference_it_matched(self):
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        _, ev, _, _ = self.go(self.task([]), ws, lambda ctx: "continue")
        rows = [json.loads(l) for l in (self.last_run_dir / "hooks.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(r["k"], r["reference"]) for r in rows], [(1, "part1"), (2, "part2"), (3, "part3")])
        self.assertIn("资料", rows[0]["clause"])

    def test_at_checkpoint_fires_after_the_part_that_passes_it(self):
        from deskmind_bench.task import Checkpoint
        ws = files_ws("draft-21.csv", "todo-94.txt", "backup/记录-30.txt")
        cp = Checkpoint(name="folder_made", check={"file_exists": {"path": "$WS/资料"}})
        t = self.task([{"id": "c3", "type": "file_moved", "trigger": {"at_checkpoint": "folder_made"},
                        "effect": [{"fs": {"op": "rm", "path": "$WS/todo-94.txt"}}]}], [cp])

        def do(sg, ws, max_actions):
            if "资料" in sg.clause:
                (ws / "资料").mkdir(exist_ok=True)
            return executor()(sg, ws, max_actions)
        seen = []
        _, _, ch, _ = self.go(t, ws, lambda ctx: seen.append(ctx.signals) or "stop", do)
        self.assertEqual([c["change_id"] for c in ch if c["t"] == "change_fired"], ["c3"])
        self.assertIn("file_missing", seen[0], "the change fired before the first decision")
