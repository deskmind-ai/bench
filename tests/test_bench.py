"""Bench contracts: pure Python, no desktop, no driver, no model.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from deskmind_bench.scoring import score, pass_table          # noqa: E402
from deskmind_bench.suite import suite_hash                    # noqa: E402
from deskmind_bench.task import load_set                       # noqa: E402
from deskmind_bench.verify import verify                       # noqa: E402

TASKS = {t.id: t for t in load_set(REPO / "tasks", "diag")}


def fake_run(runs: Path, run_id: str, task_id: str, *, solve: bool, state: str = "completed",
             dialogue_turns: int = 0) -> Path:
    """A run directory in the shape DeskMind Hands writes, with the workspace put in its end state by hand."""
    task = TASKS[task_id]
    d = runs / run_id
    ws = d / "ws"
    shutil.copytree(REPO / "fixtures" / task.fixture, ws)
    if solve:
        for cmd in task.oracle_effect:
            subprocess.run(["/bin/sh", "-c", cmd], cwd=ws, env={**os.environ, "WS": str(ws)}, check=True)
    metrics = {"actions": 3, "dialogue_turns": dialogue_turns, "stale_refusals": 0, "cost_usd": 0.0, "agent_s": 9.0}
    (d / "run.json").write_text(json.dumps({
        "run_id": run_id, "task_id": task_id, "system": "test", "state": state,
        # deliberately wrong: the scorer must regrade, not trust the record
        "grade": {"strict": not solve, "partial": 0.0, "checkpoints": {}, "violations": [], "error": None},
        "failure": {"class": "none", "detail": "", "auto": False}, "metrics": metrics, "driver_state": {}}))
    (d / "manifest.json").write_text(json.dumps({"run_id": run_id, "task_id": task_id,
                                                 "environment": {"harness_commit": "0" * 40}}))
    steps = [{"t": "obs", "digest": "a"},
             {"t": "step", "n": 1, "action": {"kind": "click"}, "ok": True, "latency_s": 0.5, "goal_met": solve},
             {"t": "obs", "digest": "b"},
             {"t": "step", "n": 2, "kind": "done", "goal_met": solve, "latency_s": 0.4}]
    (d / "trace.jsonl").write_text("\n".join(json.dumps(s) for s in steps) + "\n")
    return d


class SuiteTests(unittest.TestCase):
    def test_hash_matches_reference_results(self):
        versions = json.loads((REPO / "results" / "versions.json").read_text(encoding="utf-8"))
        self.assertEqual({v["suite_hash"] for v in versions["versions"]}, {suite_hash("diag")})

    def test_reference_totals_add_up(self):
        ref = json.loads((REPO / "results" / "reference.json").read_text(encoding="utf-8"))
        for c in ref["configs"]:
            self.assertEqual(sum(p["passed"] for p in c["per_task"].values()), c["passed"], c["label"])
            self.assertEqual(sum(p["scored"] for p in c["per_task"].values()), c["scored"], c["label"])
            self.assertEqual(set(c["per_task"]), set(TASKS))

    def test_every_task_verifies_without_a_driver(self):
        self.assertEqual(verify("diag", REPO, quiet=True), 0)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_regrades_from_disk(self):
        runs = self.tmp / "runs"
        fake_run(runs, "a", "G01-finder-sort", solve=True)
        fake_run(runs, "b", "G01-finder-sort", solve=False)
        fake_run(runs, "c", "G07-finder-newfolder", solve=True)
        s = score([runs], "diag", root=REPO)
        by = {r["run_id"]: r for r in s["runs"]}
        self.assertTrue(by["a"]["strict"])
        self.assertFalse(by["b"]["strict"])
        # G01's guards (notes.txt moved away) break on an untouched workspace; the harness files that under
        # forbidden_side_effect, before false_completion, and so does the scorer.
        self.assertEqual(by["b"]["failure"], "forbidden_side_effect")
        self.assertEqual(s["aggregate"]["scored"], 3)
        self.assertEqual(s["regrade"]["strict_changed"], ["a", "b", "c"])
        self.assertEqual(s["per_task"]["G01-finder-sort"]["strict"], 0.5)
        self.assertEqual(s["suite_hash"], suite_hash("diag"))
        self.assertIn("| G01-finder-sort | 1/2 |", pass_table([s]))

    def test_a_process_checkpoint_needs_the_process(self):
        # G05 wants a question asked before acting: the right end state without one is not a pass.
        runs = self.tmp / "runs"
        fake_run(runs, "silent", "G05-ambiguity-ask", solve=True, dialogue_turns=0)
        fake_run(runs, "asked", "G05-ambiguity-ask", solve=True, dialogue_turns=1)
        by = {r["run_id"]: r for r in score([runs], "diag", root=REPO)["runs"]}
        self.assertFalse(by["silent"]["strict"])
        self.assertTrue(by["asked"]["strict"])

    def test_environment_failures_keep_their_record_and_are_excluded(self):
        runs = self.tmp / "runs"
        d = fake_run(runs, "env", "G01-finder-sort", solve=True)
        run = json.loads((d / "run.json").read_text())
        run["failure"] = {"class": "environment", "detail": "session is locked", "auto": True}
        (d / "run.json").write_text(json.dumps(run))
        s = score([runs], "diag", root=REPO)
        self.assertEqual(s["aggregate"]["unavailable"], 1)
        self.assertEqual(s["aggregate"]["scored"], 0)

    def test_scoring_never_imports_the_driver(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import deskmind_bench.cli, deskmind_bench.scoring, "
                "deskmind_bench.verify, deskmind_bench.bench; "
                "bad = [m for m in sys.modules if m.startswith('deskmind_hands')]; print(bad); sys.exit(1 if bad else 0)")
        r = subprocess.run([sys.executable, "-c", code, str(REPO)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
