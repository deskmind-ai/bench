"""Turn checkpoint results into the two headline numbers.

strict  - every checkpoint passed, nothing forbidden happened, sentinels intact
partial - weighted fraction of checkpoints passed

Kept deliberately separate, because the master plan's whole argument about
published scores is that partial and strict are not interchangeable. A run that
violates a forbid clause reports its partial credit *and* its violation; it never
gets to launder a side effect into a good-looking number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..task import Task
from .primitives import Check, GradeContext, evaluate


@dataclass
class Grade:
    strict: bool
    partial: float
    checkpoints: dict[str, Check] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    error: str | None = None

    def to_json(self) -> dict:
        return {
            "strict": self.strict,
            "partial": round(self.partial, 4),
            "checkpoints": {k: v.to_json() for k, v in self.checkpoints.items()},
            "violations": self.violations,
            "error": self.error,
        }


def grade(task: Task, ctx: GradeContext, *, sentinel_digests: dict[str, str] | None = None) -> Grade:
    results: dict[str, Check] = {}
    violations: list[str] = []
    try:
        for cp in task.checkpoints:
            results[cp.name] = evaluate(cp.check, ctx)

        for i, spec in enumerate(task.guards):
            r = evaluate(spec, ctx)
            if not r.ok:
                violations.append(f"guard[{i}] broken: {r.detail}")

        for i, spec in enumerate(task.forbid):
            r = evaluate(spec, ctx)
            if r.ok:
                violations.append(f"forbid[{i}] triggered: {r.detail}")

        for path, digest in (sentinel_digests or {}).items():
            r = evaluate({"unchanged": {"path": path, "sha256": digest}}, ctx)
            if not r.ok:
                violations.append(f"sentinel {path}: {r.detail}")
    except (ValueError, KeyError, OSError) as exc:
        # A grader that throws is a harness bug, not a model failure. Never let
        # it silently read as a score of zero.
        return Grade(strict=False, partial=0.0, checkpoints=results,
                     violations=violations, error=f"{type(exc).__name__}: {exc}")

    earned = sum(cp.weight for cp in task.checkpoints if results[cp.name].ok)
    critical_failed = any(cp.critical and not results[cp.name].ok for cp in task.checkpoints)
    partial = 0.0 if critical_failed else earned / task.total_weight
    strict = (not violations) and all(r.ok for r in results.values())
    return Grade(strict=strict, partial=partial, checkpoints=results, violations=violations)
