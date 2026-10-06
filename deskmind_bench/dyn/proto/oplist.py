"""The file operation list (Tier O, #62; the channel of #54 and experiment 4 in #55): a planner writes a JSON list of
mkdir / move for one subgoal, code dry-runs the whole list against the folder, and only a list that passes is carried
out. Nothing here touches the screen, and nothing is ever deleted or overwritten.

OpListExecutor runs one subgoal that way behind the orchestrator. The planner is any function prompt -> text:
`HttpTextPlanner` for a local text server (the 4B, see textgen.py) or an OpenAI-style chat endpoint. #33 / #54: only a
synthetic workspace may go to a model that is not on this machine; a real folder's names stay with the local model.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path, PurePosixPath

PROMPT = """你是文件整理助手。下面是这一步要做的事和工作目录里现有的内容。你不执行任何操作，只写一份操作清单，由程序检查后执行。

可用的操作只有两种：
{{"op": "mkdir", "path": "相对路径"}}
{{"op": "move", "from": "相对路径", "to": "相对路径"}}
改名也用 move。"to" 是完整的新路径，包含文件名，不是目标文件夹。

规则：
- 路径都相对于工作目录，用 / 分隔。
- 不能删除，不能覆盖已有的文件。
- 只做这一步要做的事，别的文件和文件夹不要动。
- 操作按清单的顺序执行。

只输出一个 JSON 数组，不要解释，不要代码块标记。

工作目录现有内容（以 / 结尾的是文件夹）：
{listing}

这一步要做的事：
{goal}
"""

RETRY = """

你上一次写的清单没有通过检查，一步也没有执行：
{plan}
检查结果：{error}
请重新输出完整的清单（只输出 JSON 数组）。
"""


def listing(ws: Path) -> str:
    out = []
    for root, dirs, files in os.walk(ws):
        rel = Path(root).relative_to(ws)
        out += [(rel / d).as_posix() + "/" for d in dirs]
        out += [(rel / f).as_posix() for f in files if f != ".DS_Store"]
    return "\n".join(sorted(out))


def parse(text: str) -> list[dict]:
    """The JSON array in a reply. A missing final "]" is closed (what constrained decoding would guarantee); anything
    else wrong is a ValueError with a reason the planner can act on."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).replace("<|im_end|>", "").strip()
    a, b = text.find("["), text.rfind("]")
    if a < 0:
        raise ValueError("回复里没有 JSON 数组")
    try:
        ops = json.loads(text[a:b + 1]) if b > a else None
    except json.JSONDecodeError:
        ops = None
    if ops is None:
        try:
            ops = json.loads(text[a:].rstrip() + "]")
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(ops, list) or not all(isinstance(o, dict) for o in ops):
        raise ValueError("清单必须是由对象组成的数组")
    return ops


def _norm(p) -> str:
    if not isinstance(p, str) or not p.strip():
        raise ValueError("路径为空")
    if p.startswith(("/", "~")):
        raise ValueError(f"路径必须是相对路径：{p}")
    parts = [x for x in PurePosixPath(p.strip()).parts if x != "."]
    if not parts or ".." in parts:
        raise ValueError(f"路径不能离开工作目录：{p}")
    return "/".join(parts)


def dry_run(ops: list[dict], ws: Path) -> list[tuple[str, str, str]]:
    """The whole list checked against the folder, nothing touched: the normalised steps, or a ValueError naming the
    first step that cannot be carried out."""
    files, dirs = set(), {""}
    for root, ds, fs in os.walk(ws):
        rel = Path(root).relative_to(ws).as_posix()
        rel = "" if rel == "." else rel
        dirs.add(rel)
        files |= {f"{rel}/{f}" if rel else f for f in fs}
    steps = []
    for i, o in enumerate(ops, 1):
        kind = o.get("op")
        if kind == "mkdir":
            p = _norm(o.get("path"))
            if p in files:
                raise ValueError(f"第 {i} 步：{p} 已经是一个文件")
            if os.path.dirname(p) not in dirs:
                raise ValueError(f"第 {i} 步：上级文件夹不存在：{os.path.dirname(p)}")
            dirs.add(p)
            steps.append(("mkdir", p, ""))
        elif kind == "move":
            src, dst = _norm(o.get("from")), _norm(o.get("to"))
            if src not in files and src not in dirs:
                raise ValueError(f"第 {i} 步：要移动的东西不存在：{src}")
            if dst in files or dst in dirs:
                raise ValueError(f"第 {i} 步：目标已经存在，不能覆盖：{dst}（to 要写完整的新路径，包含文件名）")
            if os.path.dirname(dst) not in dirs:
                raise ValueError(f"第 {i} 步：目标所在的文件夹不存在：{os.path.dirname(dst)}")
            if src in files:
                files.discard(src)
                files.add(dst)
            else:
                if dst.startswith(src + "/"):
                    raise ValueError(f"第 {i} 步：不能把文件夹移进它自己：{src}")
                dirs.discard(src)
                dirs.add(dst)
                for s in (files, dirs):
                    for x in [x for x in s if x.startswith(src + "/")]:
                        s.discard(x)
                        s.add(dst + x[len(src):])
            steps.append(("move", src, dst))
        else:
            raise ValueError(f"第 {i} 步：不认识的操作 {kind!r}，只能用 mkdir 和 move")
    return steps


def carry_out(steps: list[tuple[str, str, str]], ws: Path, trace: Path | None = None) -> None:
    """Carry out checked steps; each one is a hands-style step record in `trace`, so the dyn graders see it as a
    write (graders.write_steps reads "moved ..." / "created ..." details)."""
    for kind, a, b in steps:
        t0 = time.time()
        if kind == "mkdir":
            (ws / a).mkdir(exist_ok=True)
            detail = f"created folder '{a}'"
        else:
            if (ws / b).exists():
                raise RuntimeError(f"refusing to overwrite {b}")
            os.rename(ws / a, ws / b)
            detail = f"moved '{a}' to '{b}'"
        if trace is not None:
            with trace.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": "step", "ok": True, "kind": "oplist", "detail": detail, "t_act_start": t0},
                                   ensure_ascii=False) + "\n")


class HttpTextPlanner:
    """A text planner over HTTP. kind "prompt": POST {"prompt"} -> {"text"} (textgen.py, the local 4B). kind "chat": an
    OpenAI-style /chat/completions endpoint (a frontier model; synthetic workspaces only)."""

    def __init__(self, url: str, kind: str = "prompt", model: str | None = None, token: str | None = None,
                 timeout: float = 600.0) -> None:
        self.url, self.kind, self.model, self.token, self.timeout = url, kind, model, token, timeout
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        if self.kind == "prompt":
            body = {"prompt": prompt}
        else:
            body = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.token}"} if self.token else {})}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            j = json.load(r)
        return j["text"] if self.kind == "prompt" else j["choices"][0]["message"]["content"]


class OpListExecutor:
    """Runs one subgoal as an operation list (Tier O). Asks the planner once; if the dry run refuses the list, once
    more with the reason; carries out a list that passes. "met" means a checked list was carried out, "unmet" that
    none passed the dry run (the reason is the detail). Whether the subgoal's intent was met is not this executor's
    call: the orchestrator's signals (file_missing, user interjections) and the task's checks decide that, as they do
    for hands. Every carried-out step is a write record in <run_dir>/oplist/<n>-<id>/trace.jsonl."""

    def __init__(self, planner, run_dir: Path, cloud: bool = False) -> None:
        self.planner, self.run_dir, self.cloud = planner, Path(run_dir), cloud
        self.n = 0

    def run(self, sg, ws: Path, max_actions: int, user, log, constraints: str = ""):
        from .executors import Result
        self.n += 1
        sub = f"oplist/{self.n:02d}-{sg.id}"
        (self.run_dir / sub).mkdir(parents=True, exist_ok=True)
        trace = self.run_dir / sub / "trace.jsonl"
        trace.touch()
        goal = sg.goal + (f"。{constraints}" if constraints else "")
        prompt = PROMPT.format(listing=listing(ws), goal=goal)
        replies, error, steps = [], None, None
        for attempt in range(2):
            reply = self.planner(prompt if not replies else prompt + RETRY.format(plan=replies[-1][:4000], error=error))
            replies.append(reply)
            try:
                steps, error = dry_run(parse(reply), ws), None
                break
            except ValueError as exc:
                steps, error = None, str(exc)
        calls = {"local": 0, "cloud": len(replies)} if self.cloud else {"local": len(replies), "cloud": 0}
        with trace.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": "plan", "goal": goal, "replies": replies, "error": error}, ensure_ascii=False) + "\n")
        if steps is None:
            return Result("unmet", 0, detail=f"操作清单没有通过检查：{error}", hands_run=sub, model_calls=calls)
        if len(steps) > max_actions:
            return Result("unmet", 0, detail=f"清单有 {len(steps)} 步，超过这一步的预算 {max_actions}", hands_run=sub,
                          model_calls=calls)
        carry_out(steps, ws, trace)
        return Result("met", len(steps), detail="; ".join(f"{k} {a} {b}".strip() for k, a, b in steps), hands_run=sub,
                      model_calls=calls)
