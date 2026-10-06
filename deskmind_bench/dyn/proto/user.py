"""The user the orchestrator talks to. In the bench it is scripted (#62: no LLM user): answers come from slots, an
off-slot question gets "你自己决定" and is logged as such, and interjections arrive on a queue file the runner fills."""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_REPLY = "你自己决定"


class ScriptedUser:
    def __init__(self, slots: list[dict] | None = None, queue: Path | None = None, approve_plans: bool = True) -> None:
        self.slots = slots or []          # [{"slot", "match": regex, "reply", "approve"?}]
        self.queue = Path(queue) if queue else None
        self.approve_plans = approve_plans
        self._read = 0

    def respond(self, question: str, approval: bool = False) -> tuple[str, bool, str | None]:
        for s in self.slots:
            if re.search(s["match"], question, re.I):
                return s["reply"], bool(s.get("approve", approval and self.approve_plans)), s.get("slot")
        return (("approved" if self.approve_plans else "denied") if approval else DEFAULT_REPLY,
                bool(approval and self.approve_plans), None)

    def interjections(self) -> list[str]:
        """New lines on the queue since the last read: {"text": ...} per line, written by the bench runner."""
        if not self.queue or not self.queue.exists():
            return []
        lines = [l for l in self.queue.read_text(encoding="utf-8").splitlines() if l.strip()]
        new, self._read = lines[self._read:], len(lines)
        return [json.loads(l)["text"] for l in new]
