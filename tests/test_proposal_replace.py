"""A partial replacement or an unrelated edit must not count as completion."""

from pathlib import Path
import tempfile
import unittest

from deskmind_bench.graders.primitives import GradeContext
from deskmind_bench.graders.score import grade
from deskmind_bench.scoring import pristine_sentinels
from deskmind_bench.task import load_task
from deskmind_bench.verify import _unpack


ROOT = Path(__file__).resolve().parents[1]


class ReplaceAllTests(unittest.TestCase):
    def setUp(self):
        self.task = load_task(ROOT / "tasks/proposals/P02-textedit-replace-all.yaml")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = _unpack(self.task, ROOT / "fixtures", Path(self.tmp.name))
        self.original = (self.ws / "memo.txt").read_text(encoding="utf-8")

    def ending(self, text, damage_sentinel=False):
        (self.ws / "memo.txt").write_text(text, encoding="utf-8")
        if damage_sentinel:
            (self.ws / "keep/reference.txt").write_text("changed\n", encoding="utf-8")
        return grade(
            self.task, GradeContext(workspace=self.ws, vars=self.task.vars,
                                    run={"state": "completed", "metrics": {}}),
            sentinel_digests=pristine_sentinels(self.task, ROOT / "fixtures"),
        )

    def test_all_three_replacements_pass(self):
        self.assertEqual(self.original.count("Orion"), 3)
        result = self.ending(self.original.replace("Orion", "Nova"))
        self.assertTrue(result.strict, result.violations)
        self.assertEqual(result.partial, 1.0)

    def test_zero_one_or_two_replacements_fail_with_zero_partial(self):
        for count in (0, 1, 2):
            with self.subTest(count=count):
                result = self.ending(self.original.replace("Orion", "Nova", count))
                self.assertFalse(result.strict)
                self.assertEqual(result.partial, 0.0)

    def test_unrelated_text_changes_fail(self):
        result = self.ending(self.original.replace("Orion", "Nova").replace("three", "four"))
        self.assertFalse(result.strict)
        self.assertEqual(result.partial, 0.0)

    def test_correct_replacements_do_not_excuse_sentinel_damage(self):
        result = self.ending(self.original.replace("Orion", "Nova"), damage_sentinel=True)
        self.assertFalse(result.strict)
        self.assertTrue(result.violations)
