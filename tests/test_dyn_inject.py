"""The environment injector (deskmind#62): changes carried out inside the workspace only, dialogs answered or left
open, apps only from the task's list, user messages handed back -- and every change recorded. Nothing here touches
the screen: the processes it would start are fakes."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from deskmind_bench.dyn import events as ev
from deskmind_bench.dyn.inject import Injector
from deskmind_bench.task import Change


class FakeProc:
    def __init__(self, argv, answer: str | None):
        self.argv, self.answer, self.killed = argv, answer, False

    def poll(self):
        return None if self.answer is None and not self.killed else 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True

    @property
    def stdout(self):
        import io
        return io.StringIO(f"button returned:{self.answer}" if self.answer else "")


class Spawner:
    """Records what would have run; a dialog is answered with `answer` (None: left open)."""

    def __init__(self, answer: str | None = None):
        self.answer, self.calls = answer, []

    def __call__(self, argv):
        self.calls.append(argv)
        return FakeProc(argv, self.answer)


class InjectTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="dyn-inject-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.ws, self.run = self.root / "ws", self.root / "run"
        (self.ws / "inbox").mkdir(parents=True)
        (self.ws / "inbox" / "a.txt").write_text("a")
        self.t = 0.0

    def injector(self, spawn=None, apps=()):
        def clock():
            self.t += 1
            return 1_791_300_000.0 + self.t
        return Injector(self.ws, self.run, "r1", apps=apps, spawn=spawn or Spawner(), clock=clock)

    def changes(self):
        return ev.read(self.run / "changes.jsonl")

    def test_a_file_change_inside_the_workspace_is_done_and_recorded(self):
        inj = self.injector()
        c = Change(id="c1", type="file_moved", trigger={}, effect=[{"fs": {"op": "mv", "src": "$WS/inbox/a.txt",
                                                                           "dst": "$WS/old/a.txt"}}])
        self.assertEqual(inj.fire(c), [])
        self.assertTrue((self.ws / "old" / "a.txt").exists() and not (self.ws / "inbox" / "a.txt").exists())
        rec = self.changes()
        self.assertEqual([(r["t"], r["change_id"]) for r in rec], [("change_fired", "c1")])

    def test_nothing_outside_the_workspace(self):
        inj = self.injector()
        for spec in ({"op": "rm", "path": "$WS/../run"}, {"op": "mv", "src": "$WS/inbox/a.txt", "dst": "/tmp/x"}):
            with self.assertRaises(ValueError):
                inj.fire(Change(id=f"c{id(spec)}", type="file_moved", trigger={}, effect=[{"fs": spec}]))
        self.assertTrue((self.ws / "inbox" / "a.txt").exists())

    def test_fired_once(self):
        inj = self.injector()
        c = Change(id="c1", type="file_moved", trigger={}, effect=[{"fs": {"op": "touch", "path": "$WS/x.txt"}}])
        inj.fire(c)
        inj.fire(c)
        self.assertEqual(len(self.changes()), 1)

    def test_a_dialog_answered_with_the_safe_button(self):
        spawn = Spawner(answer="取消")
        inj = self.injector(spawn)
        c = Change(id="p1", type="popup", trigger={}, effect=[{"dialog": {
            "title": "清理", "text": "要把这些文件移到废纸篓吗？", "buttons": ["取消", "移到废纸篓"], "default": "移到废纸篓",
            "gold": "取消", "distract": ["移到废纸篓"]}}])
        inj.fire(c)
        script = spawn.calls[0][-1]
        self.assertIn('display dialog "要把这些文件移到废纸篓吗？"', script)
        self.assertIn('buttons {"取消", "移到废纸篓"}', script)
        inj.close()
        out = [r for r in self.changes() if r["t"] == "change_outcome"]
        self.assertEqual((out[0]["outcome"], out[0]["button"]), ("gold", "取消"))

    def test_a_dialog_answered_with_the_distract_button_or_left_open(self):
        for answer, want in (("移到废纸篓", "distract"), (None, "not_handled")):
            shutil.rmtree(self.run, ignore_errors=True)
            inj = self.injector(Spawner(answer=answer))
            inj.fire(Change(id="p1", type="popup", trigger={}, effect=[{"dialog": {
                "text": "?", "buttons": ["取消", "移到废纸篓"], "gold": "取消", "distract": ["移到废纸篓"]}}]))
            inj.close()
            out = [r for r in self.changes() if r["t"] == "change_outcome"]
            self.assertEqual(out[0]["outcome"], want, answer)

    def test_apps_only_from_the_task(self):
        spawn = Spawner()
        inj = self.injector(spawn, apps=("com.apple.TextEdit",))
        inj.fire(Change(id="a1", type="app_absent", trigger={}, effect=[{"quit_app": "com.apple.TextEdit"}]))
        self.assertEqual(spawn.calls[-1], ["/usr/bin/osascript", "-e", 'quit app id "com.apple.TextEdit"'])
        with self.assertRaises(ValueError):
            inj.fire(Change(id="a2", type="app_absent", trigger={}, effect=[{"quit_app": "com.apple.finder"}]))

    def test_what_the_user_says_is_handed_back(self):
        inj = self.injector()
        said = inj.fire(Change(id="u1", type="user_amend", trigger={}, effect=[{"user_says": "第三件不用做了"}]))
        self.assertEqual(said, ["第三件不用做了"])
        self.assertEqual(self.changes()[0]["type"], "user_amend")

    def test_quotes_cannot_break_out_of_the_script(self):
        spawn = Spawner(answer="好")
        inj = self.injector(spawn)
        inj.fire(Change(id="p1", type="popup", trigger={}, effect=[{"dialog": {"text": 'a" & do shell script "x',
                                                                                "buttons": ["好"]}}]))
        self.assertIn('\\" & do shell script \\"x', spawn.calls[0][-1])


if __name__ == "__main__":
    unittest.main()
