"""Failure taxonomy.

Every terminated run gets exactly one primary class. Classes marked
``auto`` are decided by the harness from the trace; the rest need a human or a
judge pass. The point of the taxonomy is routing: each class maps to a different
owner and a different kind of fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureClass(str, Enum):
    NONE = "none"
    VISUAL_GROUNDING = "visual_grounding"       # right intent, wrong pixel
    PLANNING = "planning"                       # wrong intent or wrong order
    ACTION_PARSE = "action_parse"               # output was not a legal action
    WRONG_TARGET = "wrong_target"               # right action, wrong window/app/document
    INPUT_OR_CLIPBOARD = "input_or_clipboard"   # text arrived wrong or clobbered clipboard
    NO_PROGRESS_LOOP = "no_progress_loop"       # repeated states without advancing
    FALSE_COMPLETION = "false_completion"       # claimed done, grader disagrees
    BUDGET_EXHAUSTED = "budget_exhausted"       # ran out of actions or wall clock
    SYSTEM_RESOURCE = "system_resource"         # memory pressure, swap, thermal
    ENVIRONMENT = "environment"                 # fixture/reset/driver broke
    PROVIDER_UNAVAILABLE = "provider_unavailable"  # API error, model not loadable
    FORBIDDEN_SIDE_EFFECT = "forbidden_side_effect"  # touched something it must not
    HARNESS_BUG = "harness_bug"                 # our fault, not the model's


#: Classes the harness assigns itself from the trace, with no judgement call.
AUTO_CLASSIFIED = frozenset({
    FailureClass.ACTION_PARSE,
    FailureClass.BUDGET_EXHAUSTED,
    FailureClass.PROVIDER_UNAVAILABLE,
    FailureClass.ENVIRONMENT,
    FailureClass.NO_PROGRESS_LOOP,
    FailureClass.FALSE_COMPLETION,
    FailureClass.FORBIDDEN_SIDE_EFFECT,
    FailureClass.HARNESS_BUG,
})

#: Classes that must NOT be counted against the model when comparing models.
#: Report them separately as availability, per the evaluation plan.
NOT_MODEL_FAULT = frozenset({
    FailureClass.ENVIRONMENT,
    FailureClass.PROVIDER_UNAVAILABLE,
    FailureClass.HARNESS_BUG,
})


@dataclass
class Failure:
    cls: FailureClass
    detail: str = ""
    auto: bool = False

    def to_json(self) -> dict:
        return {"class": self.cls.value, "detail": self.detail, "auto": self.auto}


def no_progress(state_digests: list[str], *, window: int = 4) -> bool:
    """True when the last ``window`` observations are byte-identical.

    Deliberately strict: a real UI almost always jitters (caret blink, clock), so
    identical digests mean the agent is genuinely stuck, not merely slow.
    """
    if len(state_digests) < window:
        return False
    tail = state_digests[-window:]
    return len(set(tail)) == 1
