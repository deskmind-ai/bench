"""The living plan: subgoals with optional success checks, and the planners that write and revise it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Clause boundaries in a multi-part goal, Chinese and English. The first match splits; the rest stay with the clause.
_SPLIT = re.compile(r"[；;]|(?:，|,)?\s*(?:然后|接着|之后|再|最后|并且|then|and then|after that|finally)\s*", re.I)
# Sentences that constrain every part ("其他文件不要动") rather than being a part of their own.
_CONSTRAINT = re.compile(r"^(?:其他|其余|不要|别|do not|don't|leave)", re.I)
_FILE = re.compile(r"[\w一-鿿.\-]+\.[A-Za-z0-9]{1,6}")
_VERBS = (("mkdir", r"新建|建一个|创建|create|make a folder|new folder"),
          ("delete", r"删除|删掉|移到废纸篓|delete|trash|remove"),
          ("rename", r"改名|重命名|后缀|前缀|rename|suffix|prefix"),
          ("move", r"移到|移动|放进|放到|挪到|move|put .* into"),
          ("send", r"发送|发给|send|email"),
          ("write", r"写入|写进|追加|替换|填入|保存|write|append|replace|save"))


@dataclass
class Subgoal:
    id: str
    goal: str                        # what the executor is told; repair and ask append to it
    channel: str = "gui"
    post: str | None = None          # a named success check the executor's caller can run; None: trust the outcome
    clause: str = ""                 # the part as the plan first wrote it: what "done" is keyed on across versions

    def __post_init__(self) -> None:
        self.clause = self.clause or self.goal

    def to_event(self) -> dict:
        return {"id": self.id, "goal": self.goal, "post": self.post, "channel": self.channel}


@dataclass
class Plan:
    version: int
    by: str
    subgoals: list[Subgoal]
    constraints: str = ""
    done: list[str] = field(default_factory=list)      # ids of subgoals met under any earlier version

    def writes(self) -> list[dict]:
        """The writes the remaining subgoals would make, one per operation, with both ends relative to $WS: what
        the user is asked to confirm, and what the dyn graders hold the run to (#62)."""
        return [w for s in self.subgoals if s.id not in self.done for w in clause_writes(s.clause)]

    def remaining(self) -> list[Subgoal]:
        return [s for s in self.subgoals if s.id not in self.done]


_NAME = r"[\w\u4e00-\u9fff.\-]+"


def clause_writes(clause: str) -> list[dict]:
    """The file operations one clause asks for (Chinese and English patterns of explicit tasks), as
    {"class", "op", "src", "dst"} with paths relative to the workspace. Several per clause: "新建文件夹 资料，把
    draft-21.csv 放进去" is a mkdir and a move. Unrecognised wording yields nothing, and its writes then show up as
    unconfirmed -- the gate is what catches a planner that cannot say what it will write."""
    out: list[dict] = []
    w = lambda op, src, dst: out.append({"class": "write", "op": op, "src": src, "dst": dst})
    folder = None
    m = re.search(rf"(?:新建|创建)(?:一个)?文件夹\s*「?({_NAME})」?|(?:create|make)\s+(?:a\s+)?folder\s+({_NAME})", clause, re.I)
    if m:
        folder = m.group(1) or m.group(2)
        w("mkdir", None, folder)
    for m in re.finditer(rf"把\s*(?:({_NAME})\s*(?:里|中)的\s*)?({_NAME}\.\w+)\s*(放进去|放进|放到|移到|移动到|挪到)\s*「?({_NAME})?」?", clause):
        sub, f, verb, where = m.group(1), m.group(2), m.group(3), m.group(4)
        src = f"{sub}/{f}" if sub else f
        if verb == "放进去" or not where:
            dst = f"{folder}/{f}" if folder else None
        elif where in ("顶层", "最外层", "根目录"):
            dst = f
        else:
            dst = f"{where}/{f}"
        w("move", src, dst)
    for m in re.finditer(rf"把\s*({_NAME}\.\w+)\s*(?:改名为|重命名为|改成)\s*({_NAME}\.\w+)", clause):
        w("rename", m.group(1), m.group(2))
    for m in re.finditer(rf"给\s*({_NAME})\.(\w+)\s*加(?:上)?后缀\s*({_NAME})", clause):
        w("rename", f"{m.group(1)}.{m.group(2)}", f"{m.group(1)}{m.group(3)}.{m.group(2)}")
    for m in re.finditer(rf"(?:删除|删掉)\s*({_NAME}\.\w+)|把\s*({_NAME}\.\w+)\s*(?:删除|删掉|移到废纸篓)", clause):
        w("delete", m.group(1) or m.group(2), None)
    return out


def _clauses(goal: str) -> tuple[list[str], str]:
    # Sentence ends: 。！？, or a full stop followed by a space (not the dot in "draft-21.csv").
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])|(?<=\.)\s+", goal) if s and s.strip()]
    constraints = "".join(s for s in sentences if _CONSTRAINT.search(s))
    body = "".join(s for s in sentences if not _CONSTRAINT.search(s))
    parts = [p.strip(" ，,。.") for p in _SPLIT.split(body) if p and p.strip(" ，,。.")]
    return parts, constraints


class TemplatePlanner:
    """No model: splits an explicit multi-part goal into its clauses. Revising re-splits the goal with what the user
    has said since, and keeps what is already done. This is arm (c)'s planner in T7: the local model only decides."""

    by = "template"

    def plan(self, goal: str, channel: str = "gui") -> Plan:
        parts, constraints = _clauses(goal)
        return Plan(1, self.by, [Subgoal(f"s{i + 1}", p, channel) for i, p in enumerate(parts)], constraints)

    def replan(self, goal: str, plan: Plan, said: list[str]) -> Plan:
        """A new version of the same parts: the template cannot read an amendment ("慢一点", "第三件不用做了"), so
        what the user said is not turned into parts -- it goes to the decider, which can ask or stop. Parts already
        met stay done, by their original clause, however repair or ask edited the text sent to the executor."""
        done = {s.clause for s in plan.subgoals if s.id in plan.done}
        kept = [Subgoal(f"v{plan.version + 1}s{i + 1}", s.clause, s.channel, s.post, s.clause)
                for i, s in enumerate(plan.subgoals) if s.clause not in done]
        return Plan(plan.version + 1, self.by, kept, plan.constraints)
