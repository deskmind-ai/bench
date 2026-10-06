"""Run one goal through the Tier O orchestrator prototype.

    python -m deskmind_bench.dyn.proto "<goal>" --in <folder> --run-dir <dir> \\
        --hands ~/projj/github.com/deskmind-ai/hands --systemone-url http://127.0.0.1:8793 [--user-script slots.json]

The per-part executor is `deskmind-hands do` on the real desktop; decisions go to the Brain at --systemone-url.
Events land in <run-dir>/orchestrator.jsonl; the bench runner's changes go to <run-dir>/changes.jsonl and user
interjections to <run-dir>/user_queue.jsonl, which the orchestrator reads at decision points.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .decide import SystemOneDecider
from .events import EventLog
from .executors import HandsDoExecutor
from .orchestrator import Budget, run
from .plan import TemplatePlanner
from .user import ScriptedUser


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m deskmind_bench.dyn.proto")
    ap.add_argument("goal")
    ap.add_argument("--in", dest="into", required=True)
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--hands", required=True, help="path to the hands checkout (deskmind-hands do is run from it)")
    ap.add_argument("--systemone-url", default="http://127.0.0.1:8793")
    ap.add_argument("--token", default=os.environ.get("DESKMIND_BRAIN_TOKEN"))
    ap.add_argument("--app", default="com.apple.finder")
    ap.add_argument("--apps", default="")
    ap.add_argument("--channel", default="gui", choices=["gui", "oplist", "app"])
    ap.add_argument("--max-actions", type=int, default=60)
    ap.add_argument("--max-replans", type=int, default=3)
    ap.add_argument("--user-script", default=None, help='JSON list of {"slot", "match", "reply", "approve"?}')
    args = ap.parse_args(argv)
    rd = Path(args.run_dir or f"runs/dyn-proto-{time.strftime('%Y%m%d-%H%M%S')}")
    rd.mkdir(parents=True, exist_ok=True)
    slots = json.loads(Path(args.user_script).read_text(encoding="utf-8")) if args.user_script else []
    out = run(args.goal, Path(args.into), planner=TemplatePlanner(),
              decider=SystemOneDecider(args.systemone_url, args.token),
              executor=HandsDoExecutor(Path(args.hands), args.systemone_url, rd.resolve(), app=args.app, apps=args.apps),
              user=ScriptedUser(slots, queue=rd / "user_queue.jsonl"), log=EventLog(rd / "orchestrator.jsonl", rd.name),
              budget=Budget(max_actions=args.max_actions, max_replans=args.max_replans), channel=args.channel)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["state"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
