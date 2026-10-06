"""Carrying out a dynamic task's changes (deskmind#62): what happens to the run mid-way, done to the environment and
never through the driver -- "faults belong in the app or the environment", so the same change hits any agent under
test identically. The harness's loop decides *when* (at start, at a checkpoint, at a state, before the Nth write);
an orchestrator does the same between subgoals. Both call this.

Every change fired is recorded in ``changes.jsonl`` (events.py); a dialog's answer is recorded when the run ends.
Nothing here is shown to the agent: a user message is handed back to the caller, which delivers it as the user's.

Effects:
    fs: {op: mv | rm | touch | write | mkdir, src, dst | path, text}   inside the workspace, never the workspace itself
    dialog: {title, text, buttons, default, gold, distract,             a real `display dialog`, answered or not
             giving_up_after}

A change is checked whole before any of it is carried out: one refused effect leaves the others undone.
    notify: {title, text}                                               a notification banner, non-blocking
    quit_app: <bundle id> / launch_app: <bundle id>                     only bundles the task allows
    user_says: <text>                                                   handed back for the user channel
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import events as ev

Runner = Callable[[list[str]], subprocess.Popen]


def _spawn(argv: list[str]) -> subprocess.Popen:
    return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _as(s: str) -> str:
    """A string as an AppleScript literal."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


class Injector:
    def __init__(self, ws: Path, run_dir: Path, run_id: str, *, apps: tuple[str, ...] = (),
                 spawn: Runner = _spawn, clock: Callable[[], float] = time.time) -> None:
        self.ws, self.run_dir, self.run_id = Path(ws).resolve(), Path(run_dir), run_id
        self.apps = set(apps)
        self.spawn, self.clock = spawn, clock
        self.dialogs: list[tuple[str, dict, subprocess.Popen]] = []
        self.fired: set[str] = set()

    # -- the record -----------------------------------------------------------

    def _write(self, event: dict) -> None:
        event = {"v": ev.VERSION, "ts": self.clock(), "run": self.run_id, **event}
        bad = ev.validate(event)
        if bad:
            raise ValueError("; ".join(bad))
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "changes.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # -- effects --------------------------------------------------------------

    def _path(self, s: str, *, root_ok: bool = False) -> Path:
        """A path inside the workspace. The workspace itself only where that is harmless (mkdir): removed or moved
        away, it would take the run's ground truth with it."""
        p = Path(str(s).replace("$WS", str(self.ws))).resolve()
        if p == self.ws and not root_ok:
            raise ValueError(f"a change may not remove or move the workspace itself: {s!r}")
        if p != self.ws and self.ws not in p.parents:
            raise ValueError(f"a change may only touch the workspace: {s!r}")
        return p

    _FS_OPS = ("mv", "rename", "rm", "mkdir", "touch", "write")

    def _check(self, change) -> None:
        """Every effect of a change checked before any is carried out, so a refused one leaves nothing half done."""
        for eff in change.effect:
            (kind, spec), = eff.items()
            if kind == "fs":
                if spec.get("op") not in self._FS_OPS:
                    raise ValueError(f"unknown fs op {spec.get('op')!r}")
                for key in ("src", "dst", "path"):
                    if key in spec:
                        self._path(spec[key], root_ok=spec["op"] == "mkdir")
            elif kind in ("quit_app", "launch_app"):
                if str(spec) not in self.apps:
                    raise ValueError(f"the task does not allow changes to {spec!r}")
            elif kind not in ("dialog", "notify", "user_says"):
                raise ValueError(f"unknown effect {kind!r}")

    def _fs(self, spec: dict) -> None:
        op = spec["op"]
        if op in ("mv", "rename"):
            src, dst = self._path(spec["src"]), self._path(spec["dst"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        elif op == "rm":
            p = self._path(spec["path"])
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        elif op == "mkdir":
            self._path(spec["path"], root_ok=True).mkdir(parents=True, exist_ok=True)
        elif op in ("touch", "write"):
            p = self._path(spec["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            if op == "touch":
                p.touch()
            else:
                p.write_text(str(spec.get("text", "")), encoding="utf-8")
        else:
            raise ValueError(f"unknown fs op {op!r}")

    def _dialog(self, change_id: str, spec: dict) -> None:
        buttons = list(spec.get("buttons") or ["好"])
        script = (f"display dialog {_as(spec.get('text', ''))} with title {_as(spec.get('title', ''))} "
                  f"buttons {{{', '.join(_as(b) for b in buttons)}}}"
                  + (f" default button {_as(spec['default'])}" if spec.get("default") else "")
                  # A dialog nobody answers closes by itself after this long and counts as not handled.
                  + (f" giving up after {int(spec['giving_up_after'])}" if spec.get("giving_up_after") else ""))
        self.dialogs.append((change_id, spec, self.spawn(["/usr/bin/osascript", "-e", script])))

    def _app(self, bundle: str, quit_: bool) -> None:
        if bundle not in self.apps:
            raise ValueError(f"the task does not allow changes to {bundle!r}")
        argv = (["/usr/bin/osascript", "-e", f"quit app id {_as(bundle)}"] if quit_
                else ["/usr/bin/open", "-g", "-b", bundle])
        self.spawn(argv).wait(timeout=30)

    def fire(self, change) -> list[str]:
        """Carry out one change (task.Change), once; returns what the user says, for the caller to deliver."""
        if change.id in self.fired:
            return []
        self._check(change)
        self.fired.add(change.id)
        said = []
        for eff in change.effect:
            (kind, spec), = eff.items()
            if kind == "fs":
                self._fs(spec)
            elif kind == "dialog":
                self._dialog(change.id, spec)
            elif kind == "notify":
                self.spawn(["/usr/bin/osascript", "-e", f"display notification {_as(spec.get('text', ''))} "
                            f"with title {_as(spec.get('title', ''))}"]).wait(timeout=30)
            elif kind in ("quit_app", "launch_app"):
                self._app(str(spec), quit_=kind == "quit_app")
            elif kind == "user_says":
                said.append(str(spec))
            else:
                raise ValueError(f"unknown effect {kind!r}")
        self._write({"t": "change_fired", "change_id": change.id, "type": change.type, "effect": change.effect})
        return said

    def close(self) -> None:
        """At the end of the run: how each dialog was answered, and any still open is closed (not_handled)."""
        for change_id, spec, proc in self.dialogs:
            if proc.poll() is None:
                proc.kill()
                outcome, button = "not_handled", None
            else:
                out = (proc.stdout.read() if proc.stdout else "") or ""
                button = (out.split("button returned:", 1)[1].split(",", 1)[0].strip() or None
                          if "button returned:" in out and "gave up:true" not in out else None)
                outcome = ("gold" if button == spec.get("gold") else
                           "distract" if button in (spec.get("distract") or []) else
                           "not_handled" if button is None else "other")
            self._write({"t": "change_outcome", "change_id": change_id, "outcome": outcome, "button": button})
        self.dialogs = []
