"""A model writes the plan; code checks it before anyone sees it (#60, T7's model-planner arms).

The model is shown the goal, the workspace's files and what the user has said, and answers with JSON: the parts, each
with the file operations it will make, or one question for the user. Code then plays every operation on a virtual
copy of the workspace (the op-list channel's dry run, phase-0 experiment 4): a file that is not there, a target that
already exists, a path outside the workspace -- any of these sends the whole plan back with the reasons, once, and a
second failure is an error rather than a plan nobody checked.

The declared operations are what the user confirms and what the graders hold the run to, so a model planner does not
depend on clause_writes' wording patterns. Where the model comes from is a function from messages to text: the local
4B behind an OpenAI-compatible server (mlx_lm.server), or a frontier model.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .plan import Plan, Subgoal

OPS = ("mkdir", "move", "copy", "delete")
MAX_FILES = 200

SYSTEM = """You plan file tasks on a Mac for a user. You never act yourself: an executor carries out one part at a time, \
and code checks your plan against the real files before the user sees it.

Answer with one JSON object and nothing else, in one of two forms.

A plan:
{"parts": [{"goal": "<one part, in the user's language, naming the files it acts on>",
            "done_when": "<what the screen shows when this part is done, if no file shows it>",
            "writes": [{"op": "mkdir", "dst": "<folder>"},
                       {"op": "move", "src": "<file>", "dst": "<folder>/<file>"},
                       {"op": "copy", "src": "<file>", "dst": "<folder>/<new file>"},
                       {"op": "delete", "src": "<file>"}]}]}

A question, when the goal leaves something open that the files cannot settle:
{"ask": "<one short question, in the user's language>"}

Rules:
- Paths are relative to the workspace, exactly as listed. A rename is a move.
- List every file operation of a part in its "writes", in order; a part that only reads has none.
- Do only what the goal and the user asked. Follow every constraint ("其他文件不要动").
- Keep parts that are already done out of a revised plan.
- "done_when" is for parts whose result is on screen rather than in a file (a message sent, a setting changed); \
leave it out when the writes show it."""


SYSTEM_NUMBERED = """You plan file tasks on a Mac for a user. You never act yourself: an executor carries out one part at a time, \
and code checks your plan against the real files before the user sees it.

The files and folders are listed with numbers. Point at them by number; never copy a name. Code builds the paths.

Answer with one JSON object and nothing else, in one of two forms.

A plan:
{"parts": [{"goal": "<one part, in the user's language>",
            "writes": [{"op": "mkdir", "to": "<new folder path>"},
                       {"op": "move", "file": <number>, "to": "<target folder; \"\" for the top level>", "rename": "<new name, only when renaming>"},
                       {"op": "copy", "file": <number>, "to": "<target folder>", "rename": "<name of the copy, optional>"},
                       {"op": "delete", "file": <number>}]}]}

A question, when the goal leaves something open that the files cannot settle:
{"ask": "<one short question, in the user's language>"}

Rules:
- A rename is a move with "rename" (and "to" the folder it is in).
- List every file operation of a part in its "writes", in order; a part that only reads has none.
- Do only what the goal and the user asked. Follow every constraint ("其他文件不要动").
- Keep parts that are already done out of a revised plan."""


def entries(ws: Path) -> list[str]:
    """The workspace listing in the order it is numbered for the model: what `file` numbers refer to."""
    return sorted(tree(ws))


_ALIASES = {"mv": "move", "rename": "move", "ren": "move", "cp": "copy", "md": "mkdir", "mkdirs": "mkdir", "rm": "delete"}


def from_numbered(writes: list, listing: list[str]) -> tuple[list[dict], list[str]]:
    """The model's numbered writes ({"file": n, "to", "rename"}) as plain src/dst writes, built by code; problems in
    words for the model. A rename keeps the extension unless the new name gives one."""
    out, problems = [], []
    for i, w in enumerate(writes if isinstance(writes, list) else [], 1):
        if not isinstance(w, dict):
            problems.append(f"write {i}: not an object")
            continue
        # The 4B writes shell-ish names (T7 dev, numbered form: 'mv', 'cp', 'rename'); a rename is a move with "rename"
        op = _ALIASES.get(str(w.get("op") or "").strip().lower(), w.get("op"))
        if w.get("op") == "rename" and "to" not in w:   # {"op": "rename", "file": n, "rename": x}: stays in its folder
            w = {**w, "to": None}
        if op == "mkdir":
            to = (w.get("to") or w.get("dst") or "").strip().strip("/")
            if not to:
                problems.append(f"write {i} (mkdir): needs \"to\"")
            else:
                out.append({"op": "mkdir", "dst": to})
            continue
        try:
            n = int(w.get("file"))
        except (TypeError, ValueError):
            problems.append(f"write {i} ({op}): \"file\" must be a number from the list")
            continue
        if not 1 <= n <= len(listing):
            problems.append(f"write {i} ({op}): there is no file {n}")
            continue
        src = listing[n - 1].rstrip("/")
        if op == "delete":
            out.append({"op": "delete", "src": src})
            continue
        if op not in ("move", "copy"):
            problems.append(f"write {i}: unknown operation {op!r}")
            continue
        to = w.get("to", "")
        if to is None:   # a rename without a target folder: the folder the file is in
            to = str(Path(src).parent) if "/" in src else ""
        if not isinstance(to, str):
            problems.append(f"write {i} ({op}): \"to\" must be a folder path")
            continue
        name = w.get("rename") or Path(src).name
        if not isinstance(name, str) or "/" in name or not name.strip():
            problems.append(f"write {i} ({op}): \"rename\" must be a plain file name")
            continue
        to = to.strip().strip("/")
        out.append({"op": op, "src": src, "dst": f"{to}/{name.strip()}" if to else name.strip()})
    return out, problems


@dataclass
class Checked:
    ok: bool
    problems: list[str]              # for the model, in words
    missing: list[str] = None        # sources that were not there, as paths: what signals.file_missing reads

    def __post_init__(self) -> None:
        self.missing = self.missing or []


def tree(ws: Path) -> set[str]:
    """Every file and folder under the workspace, relative, folders ending in '/'."""
    out = set()
    for p in ws.rglob("*"):
        rel = p.relative_to(ws).as_posix()
        if any(part.startswith(".") for part in Path(rel).parts):   # hidden files, and the harness's own .hands/
            continue
        out.add(rel + "/" if p.is_dir() else rel)
    return out


def dry_run(writes: list[dict], files: set[str]) -> Checked:
    """Play the writes on a virtual tree, in order. Every problem is listed, and nothing is changed."""
    have = set(files)
    problems: list[str] = []
    missing: list[str] = []

    def bad(p: str | None) -> str | None:
        if not p:
            return "a path is missing"
        if p.startswith("/") or p.startswith("~") or ".." in Path(p).parts:
            return f"{p!r} is outside the workspace"
        return None

    def exists(p: str) -> bool:
        return p.rstrip("/") in have or p.rstrip("/") + "/" in have

    def parent_ok(p: str) -> bool:
        parent = Path(p).parent.as_posix()
        return parent == "." or parent + "/" in have

    for i, w in enumerate(writes, 1):
        op, src, dst = w.get("op"), w.get("src"), w.get("dst")
        where = f"write {i} ({op})"
        if op not in OPS:
            problems.append(f"{where}: unknown operation; use one of {', '.join(OPS)}")
            continue
        for p in ([src] if op in ("move", "copy", "delete") else []) + ([dst] if op in ("mkdir", "move", "copy") else []):
            if (e := bad(p)):
                problems.append(f"{where}: {e}")
        if problems and problems[-1].startswith(where):
            continue
        if op == "mkdir":
            if exists(dst):
                problems.append(f"{where}: {dst!r} already exists")
            elif not parent_ok(dst):
                problems.append(f"{where}: the folder {Path(dst).parent.as_posix()!r} does not exist")
            else:
                have.add(dst.rstrip("/") + "/")
        elif op == "copy":
            if not exists(src):
                problems.append(f"{where}: {src!r} is not there")
                missing.append(src)
            elif exists(dst):
                problems.append(f"{where}: {dst!r} already exists")
            elif not parent_ok(dst):
                problems.append(f"{where}: the folder {Path(dst).parent.as_posix()!r} does not exist")
            else:
                s_, d_ = src.rstrip("/"), dst.rstrip("/")
                have |= {d_ + p[len(s_):] for p in have if p == s_ or p == s_ + "/" or p.startswith(s_ + "/")}
        elif op == "move":
            if not exists(src):
                problems.append(f"{where}: {src!r} is not there")
                missing.append(src)
            elif exists(dst):
                problems.append(f"{where}: {dst!r} already exists")
            elif not parent_ok(dst):
                problems.append(f"{where}: the folder {Path(dst).parent.as_posix()!r} does not exist")
            else:
                is_dir = src.rstrip("/") + "/" in have
                s, d = src.rstrip("/"), dst.rstrip("/")
                moved = {p for p in have if p == s or p == s + "/" or p.startswith(s + "/")}
                have -= moved
                have |= {d + p[len(s):] for p in moved}
                if is_dir:
                    have.add(d + "/")
        else:
            if not exists(src):
                problems.append(f"{where}: {src!r} is not there")
                missing.append(src)
            else:
                s = src.rstrip("/")
                have -= {p for p in have if p == s or p == s + "/" or p.startswith(s + "/")}
    return Checked(not problems, problems, missing)


def parse(text: str) -> dict:
    """The first JSON object in the reply (a model may wrap it in a fence or a sentence, or add a second object after
    it: raw_decode reads one object from the first "{" and ignores what follows)."""
    i = text.find("{")
    if i < 0:
        raise ValueError("no JSON object in the reply")
    obj, _ = json.JSONDecoder().raw_decode(text[i:])
    if not isinstance(obj, dict):
        raise ValueError("the reply's JSON is not an object")
    return obj


def normalise(writes: list[dict], files: set[str]) -> list[dict]:
    """A move or copy whose dst is a folder (one that exists, or that an earlier write makes) goes into it under the
    source's name: "move a.txt -> 资料" means 资料/a.txt. The local model writes this often, and it is never a request
    to overwrite a folder. Everything else is left as written."""
    folders = {p.rstrip("/") for p in files if p.endswith("/")}
    out = []
    for w in writes:
        w = dict(w)
        if w.get("op") == "mkdir" and w.get("dst"):
            folders.add(w["dst"].rstrip("/"))
        if w.get("op") in ("move", "copy") and w.get("src") and w.get("dst") and w["dst"].rstrip("/") in folders:
            w["dst"] = f"{w['dst'].rstrip('/')}/{Path(w['src'].rstrip('/')).name}"
        out.append(w)
    return out


def _shape(obj: dict) -> list[str]:
    if isinstance(obj.get("ask"), str) and obj["ask"].strip():
        return []
    parts = obj.get("parts")
    if not isinstance(parts, list) or not parts:
        return ['the answer needs "parts" (a non-empty list) or "ask"']
    out = []
    for i, p in enumerate(parts, 1):
        if not isinstance(p, dict) or not isinstance(p.get("goal"), str) or not p["goal"].strip():
            out.append(f'part {i}: needs a "goal"')
        elif not isinstance(p.get("writes", []), list):
            out.append(f'part {i}: "writes" must be a list')
    return out


class PlanFailed(Exception):
    """The model's plan failed the checks twice. The orchestrator ends the run; it never runs an unchecked plan."""


class ModelPlanner:
    def __init__(self, complete: Callable[[list[dict]], str], by: str = "local-4b", rewrites: int = 1,
                 peek_bytes: int = 0, peek_files: int = 20, form: str = "paths", precheck=None) -> None:
        """peek_bytes > 0 shows the planner the text of small files (at most peek_files of them, each at most peek_bytes):
        for tasks whose next step depends on what a file says (#62 BR). Only for workspaces the bench generates: a
        real folder's contents must not go to a model that is not on the machine (#33)."""
        self.complete, self.by, self.rewrites = complete, by, rewrites
        self.peek_bytes, self.peek_files = peek_bytes, peek_files
        if form not in ("paths", "numbered"):
            raise ValueError(f"form must be paths or numbered, not {form!r}")
        # "numbered" (T7 amendment 4): the model points at files by number and code builds the paths -- copying a name
        # exactly is code's job; the untrained 4B spaces out and mixes up names it copies.
        self.form = form
        # precheck(goal, listing, said) -> bool: is the method settled? (T7 arm e). When it says no, the plan opens
        # with a question instead of a guess -- the 4B rarely asks unprompted, but answers this one question well.
        self.precheck = precheck
        self.calls = 0
        self.question: str | None = None

    def _prompt(self, goal: str, ws: Path, said: list[str], done: list[str], why: str | None) -> str:
        files = entries(ws)
        shown = [f"{i + 1}. {f}" for i, f in enumerate(files)] if self.form == "numbered" else files
        listing = "\n".join(shown[:MAX_FILES]) + (f"\n… ({len(files) - MAX_FILES} more)" if len(files) > MAX_FILES else "")
        lines = [f"Goal: {goal}", "", "Files in the workspace:", listing or "(empty)"]
        if self.peek_bytes:
            shown = []
            for rel in files:
                if rel.endswith("/") or len(shown) >= self.peek_files:
                    continue
                p = ws / rel
                try:
                    if p.stat().st_size <= self.peek_bytes:
                        shown.append(f"--- {rel}\n{p.read_text(encoding='utf-8').rstrip()}")
                except (OSError, UnicodeDecodeError):
                    continue
            if shown:
                lines += ["", "Contents of the small text files:", *shown]
        if done:
            lines += ["", "Already done (keep these out of the plan):", *[f"- {d}" for d in done]]
        if why:
            lines += ["", f"Why the plan is being revised: {why}"]
        if said:
            lines += ["", "What the user has said:", *[f"- {s}" for s in said]]
        return "\n".join(lines)

    def _write(self, goal: str, ws: Path, said: list[str], done: list[str], why: str | None) -> dict:
        msgs = [{"role": "system", "content": SYSTEM_NUMBERED if self.form == "numbered" else SYSTEM},
                {"role": "user", "content": self._prompt(goal, ws, said, done, why)}]
        listing = entries(ws)
        problems: list[str] = []
        for attempt in range(self.rewrites + 1):
            if attempt:
                msgs += [{"role": "user", "content": "The plan was not accepted:\n" +
                          "\n".join(f"- {p}" for p in problems) + "\nWrite the whole answer again."}]
            self.calls += 1
            reply = self.complete(msgs)
            msgs.append({"role": "assistant", "content": reply})
            try:
                obj = parse(reply)
            except ValueError as exc:
                problems = [f"the answer is not JSON: {exc}"]
                continue
            problems = _shape(obj)
            if not problems and self.form == "numbered" and "parts" in obj and not obj.get("ask"):
                for p in obj["parts"]:
                    p["writes"], bad = from_numbered(p.get("writes") or [], listing)
                    problems += bad
            if not problems and "parts" in obj and not obj.get("ask"):
                files = tree(ws)
                seen = set(files)
                for p in obj["parts"]:   # normalise in plan order, so a folder made by an earlier part counts
                    p["writes"] = normalise(p.get("writes") or [], seen)
                    seen |= {w["dst"].rstrip("/") + "/" for w in p["writes"] if w.get("op") == "mkdir" and w.get("dst")}
                writes = [w for p in obj["parts"] for w in p.get("writes") or []]
                problems = dry_run(writes, files).problems
            if not problems:
                return obj
        raise PlanFailed("; ".join(problems))

    def _plan(self, obj: dict, version: int, channel: str, prefix: str, constraints: str = "") -> Plan:
        self.question = obj.get("ask") if not obj.get("parts") else None
        subgoals = [Subgoal(f"{prefix}{i + 1}", p["goal"].strip(), channel, (p.get("done_when") or None),
                            p["goal"].strip(),
                            writes=[{"class": "write", "op": w["op"], "src": w.get("src"), "dst": w.get("dst")}
                                    for w in p.get("writes") or []])
                    for i, p in enumerate(obj.get("parts") or [])]
        return Plan(version, self.by, subgoals, constraints, question=self.question)

    def plan(self, goal: str, channel: str = "gui", *, ws: Path | None = None, said: list[str] | None = None) -> Plan:
        said = list(said or [])
        # The precheck is asked once, before the user has said anything: after an answer the planner plans (or asks in
        # its own words). Asking it again looped until the dialogue budget ran out on a goal the answer had settled.
        if self.precheck is not None and not said and not self.precheck(goal, entries(Path(ws)), said):
            return self._plan({"ask": self._question(goal, Path(ws), said)}, 1, channel, "s")
        return self._plan(self._write(goal, Path(ws), said, [], None), 1, channel, "s")

    def _question(self, goal: str, ws: Path, said: list[str]) -> str:
        """The question to open with when the precheck says the method is not settled: the model's own, or a plain one."""
        msgs = [{"role": "system", "content": "The user's request leaves open how to do it. Ask the user one short "
                                              "question that settles it, in the user's language. Answer with one JSON "
                                              "object: {\"ask\": \"...\"}"},
                {"role": "user", "content": self._prompt(goal, ws, said, [], None)}]
        self.calls += 1
        try:
            q = parse(self.complete(msgs)).get("ask")
        except ValueError:
            q = None
        return q.strip() if isinstance(q, str) and q.strip() else "要按什么方式整理这些文件？"

    def replan(self, goal: str, plan: Plan, said: list[str], *, ws: Path | None = None, why: str | None = None,
               done: list[str] | None = None) -> Plan:
        """`done`: every part met under any version so far (the orchestrator's record); without it, this version's."""
        done = list(done) if done is not None else [s.goal for s in plan.subgoals if s.id in plan.done]
        v = plan.version + 1
        new = self._plan(self._write(goal, Path(ws), list(said), done, why), v, plan.subgoals[0].channel
                         if plan.subgoals else "gui", f"v{v}s", plan.constraints)
        new.done = []
        return new


def openai_chat(base_url: str, model: str, api_key: str | None = None, timeout: float = 120.0,
                max_tokens: int = 1024) -> Callable[[list[dict]], str]:
    """An OpenAI-compatible chat endpoint: mlx_lm.server for the local 4B, or a frontier provider. Greedy."""
    url = base_url.rstrip("/") + "/chat/completions"

    def complete(messages: list[dict]) -> str:
        body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", **({"Authorization": f"Bearer {api_key}"} if api_key else {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"]
    return complete
