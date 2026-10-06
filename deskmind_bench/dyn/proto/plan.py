"""The living plan: subgoals with optional success checks, and the planners that write and revise it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

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
    goal: str
    channel: str = "gui"
    post: str | None = None          # a named success check the executor's caller can run; None: trust the outcome

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
        """The writes the remaining subgoals would make, as the user is asked to confirm them (best effort)."""
        out = []
        for s in self.subgoals:
            if s.id in self.done:
                continue
            for op, pat in _VERBS:
                if re.search(pat, s.goal, re.I):
                    files = _FILE.findall(s.goal)
                    out.append({"class": "write", "op": op, "src": files[0] if files else None,
                                "dst": files[1] if len(files) > 1 else None})
                    break
        return out

    def remaining(self) -> list[Subgoal]:
        return [s for s in self.subgoals if s.id not in self.done]


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
        new = self.plan(goal + "".join(f"；{s}" for s in said), plan.subgoals[0].channel if plan.subgoals else "gui")
        done_text = {s.goal for s in plan.subgoals if s.id in plan.done}
        kept = [replace(s, id=f"v{plan.version + 1}s{i + 1}") for i, s in enumerate(new.subgoals) if s.goal not in done_text]
        return Plan(plan.version + 1, self.by, kept, new.constraints or plan.constraints, done=[])
