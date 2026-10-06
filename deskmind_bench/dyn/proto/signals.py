"""Deviation signals, detected by code after each subgoal (#60): the orchestrator never asks a model to notice them."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .plan import _FILE, Plan


def where_expected(goal: str, name: str, ws: Path) -> bool:
    """Whether `name` is where the goal says it is: at the top of the workspace, or in a folder the goal names
    ("backup 里的 记录-30.txt"). Somewhere else in the tree does not count: that is the file having been moved."""
    if (ws / name).exists():
        return True
    folders = [d for d in ws.rglob("*") if d.is_dir() and d.name in goal]
    return any((d / name).exists() for d in folders)


def missing_files(plan: Plan, ws: Path) -> list[str]:
    """Files the remaining subgoals act on that are not where the goal says they are.

    Only the first file a subgoal names counts, the one it acts on; a target name ("改名为 X.txt") is supposed not to
    exist yet."""
    out = []
    for s in plan.remaining():
        files = _FILE.findall(s.goal)
        if files and not where_expected(s.goal, files[0], ws):
            out.append(files[0])
    return out


def app_absent(bundle_ids: list[str]) -> list[str]:
    """Apps the task needs that are not running (osascript; nothing is started)."""
    out = []
    for b in bundle_ids:
        r = subprocess.run(["osascript", "-e", f'application id "{b}" is running'], capture_output=True, text=True)
        if r.stdout.strip() != "true":
            out.append(b)
    return out


def detect(*, outcome: str, detail: str, plan: Plan, ws: Path | None, interjections: list[str],
           actions_used: int, actions_total: int, parts_done: int, parts_total: int,
           apps: list[str] | None = None, check_apps: bool = False) -> list[str]:
    sigs: list[str] = []
    if outcome != "met":
        sigs.append("post_mismatch")
    if re.search(r"already exists|已存在|is another file's name", detail or "", re.I):
        sigs.append("write_conflict")
    if ws is not None and missing_files(plan, ws):
        sigs.append("file_missing")
    if check_apps and apps and app_absent(apps):
        sigs.append("app_absent")
    if interjections:
        sigs.append("user_interjected")
    # Half the actions spent, not half the parts done: the run will not finish at this pace.
    if actions_total and actions_used >= actions_total / 2 and parts_total and parts_done < parts_total / 2:
        sigs.append("budget_half")
    return sigs
