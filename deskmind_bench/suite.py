"""The suite hash: every file that can move a score, in one 12-character digest.

Tasks of the set, the fixtures they use, and the grader code. Two results are comparable only when their suite hash
matches *and* they were produced by the same harness version (see results/versions.md): the hash pins what is being
asked and how it is graded, the harness version pins how the desktop was presented and driven.

The graders are hashed under the path they had in the harness this suite was developed in (``hands/graders/``), so
the published suite reproduces the hash recorded next to every reference number: ``5eec62a0c662`` for diag.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GRADERS = Path(__file__).resolve().parent / "graders"
#: The path label the grader files are hashed under (see the module docstring).
GRADERS_LABEL = "hands/graders"


def suite_files(task_set: str, root: str | Path | None = None) -> list[tuple[str, Path]]:
    from .task import load_set
    root = Path(root) if root else REPO
    files = sorted((root / "tasks" / task_set).glob("*.yaml"))
    fixtures = sorted({t.fixture for t in load_set(root / "tasks", task_set) if t.fixture})
    for fx in fixtures:
        files += sorted(p for p in (root / "fixtures" / fx).rglob("*") if p.is_file())
    out = [(str(p.relative_to(root)), p) for p in files]
    out += [(f"{GRADERS_LABEL}/{p.name}", p) for p in sorted(GRADERS.glob("*.py"))]
    return out


def suite_hash(task_set: str, root: str | Path | None = None) -> str:
    h = hashlib.sha256()
    for label, p in suite_files(task_set, root):
        h.update(label.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]
