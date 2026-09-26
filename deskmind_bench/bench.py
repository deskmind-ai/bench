"""Score one System One checkpoint end to end on a DeskMind Bench task set, and write a JSON summary.

Made for a routine outer regression: every DeskMind Brain checkpoint, same tasks, same numbers, comparable over time.

    deskmind-bench run --set diag --repeats 3 --url http://127.0.0.1:8797 --label g8 --out g8-diag.json
    deskmind-bench run --set diag  --repeats 1 --url http://127.0.0.1:8797 --label g8 --projection off --out ...

No API spend: the planner is the local server at --url, a hosted key (SYSTEMONE_API_KEY) is removed from the environment so it can
never be sent anywhere, and a non-local URL is refused unless --allow-remote. `diag` drives the real Finder and TextEdit through Peekaboo and needs its Screen
Recording and Accessibility grants.

What the summary adds over a DeskMind Hands report:
  - DONE timing: the step at which the task's checker first passed (the workspace is graded after every action)
    and the step at which the model chose DONE, or "never". A model that gets there and keeps going reads as a
    failure in the final grade and as "late DONE" here -- they are different problems with different fixes.
  - the action-outcome log: per step, operation, target label, ok/error and whether the screen changed.
  - latency p50/p95 per decision, projection on/off, and a suite version that changes whenever a task, fixture or
    grader does, so numbers from different versions are never compared by accident.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: Bumped by hand when the meaning of a number changes without a file changing (a new failure rule in the loop, a
#: different budget policy). File changes are caught by suite_hash on their own.
SUITE_VERSION = "21"  # 21: a colon after an ASCII word ("Status: final，") is not dictation, so no "final，" candidate. 20: the C036 fixes (task app switchable back to, file-name guard, scratch cmd+S via save-as, unreadable windows refused, 分别 values split) and the hidden-state sweep (newfolder value shown, effects in parseable form, saves undone by edits, pending save-as per window). 19: FOCUS_WINDOW offered with one other window; scratch TextEdit windows say what they are; TextEdit saves verified by `modified` (18: quoted-line value blocks)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def suite_hash(task_set: str) -> str:
    """Tasks of the set, the fixtures they use, and the grader code -- anything that can move a score."""
    from deskmind_bench.suite import suite_hash as _suite_hash
    return _suite_hash(task_set, REPO)


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 3)


def _decision(raw):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return {"raw": raw}


def run_summary(run: dict, runs_dir: Path) -> dict:
    trace = runs_dir / run["run_id"] / "trace.jsonl"
    entries = [json.loads(l) for l in trace.open()] if trace.exists() else []
    log, latencies = [], []
    first_met = done_step = None
    last_obs = None
    pending = None                                 # the action step whose next observation decides page_changed
    for e in entries:
        if e["t"] == "obs":
            if pending is not None and last_obs is not None:
                pending["page_changed"] = e.get("digest") != last_obs
            pending, last_obs = None, e.get("digest")
            continue
        if e["t"] != "step":
            continue
        n = e.get("n")
        if e.get("latency_s"):
            latencies.append(e["latency_s"])
        if e.get("goal_met") and first_met is None:
            first_met = n
        if "action" in e:
            row = {"n": n, "op": e["action"].get("kind"), "target": e.get("target_label"),
                   "text": e["action"].get("text"), "keys": e["action"].get("keys"), "ok": e.get("ok"),
                   "error": e.get("detail") if e.get("ok") is False else None,
                   "page_changed": None, "goal_met": e.get("goal_met"), "decision": _decision(e.get("decision"))}
            pending = row
        elif e.get("kind") in ("done", "give_up"):
            row = {"n": n, "op": e["kind"], "goal_met": e.get("goal_met"), "decision": _decision(e.get("decision"))}
            if e["kind"] == "done":
                done_step = n
        elif "question" in e:
            row = {"n": n, "op": e.get("kind"), "question": e.get("question"), "reply": e.get("reply")}
        else:
            row = {"n": n, "op": "invalid", "error": e.get("parse_error") or e.get("injection")}
        log.append(row)
    failure = (run.get("failure") or {}).get("class")
    grade = run.get("grade") or {}
    return {
        "task_id": run["task_id"], "run_id": run["run_id"],
        "strict": grade.get("strict"), "partial": grade.get("partial"),
        "failure": failure, "no_progress_loop": failure == "no_progress_loop",
        "unavailable": failure in ("provider_unavailable", "environment", "harness_bug"),
        "steps": len(log), "actions": (run.get("metrics") or {}).get("actions"),
        "latency_s": {"p50": pct(latencies, .5), "p95": pct(latencies, .95), "n": len(latencies)},
        "done_timing": {
            "goal_first_met_step": first_met,
            "done_step": done_step if done_step is not None else "never",
            # DONE chosen while the checker did not pass: the other half of the DONE head's errors.
            "false_done": done_step is not None and not grade.get("strict"),
            "goal_met_at_done": (done_step is not None
                                 and next((r.get("goal_met") for r in log if r.get("n") == done_step - 1), False)
                                 is True),
            "stop_by": next(((r.get("decision") or {}).get("stop_by") for r in log if r.get("op") == "done"), None),
            # Actions spent after the goal was first met, DONE excluded: the cost of not stopping.
            "wasted_after_goal": (sum(1 for r in log if first_met is not None and r.get("n", 0) > first_met
                                      and r.get("op") not in ("done", "give_up"))),
            "lag": (done_step - first_met) if (done_step is not None and first_met is not None) else None,
        },
        "driver_state": run.get("driver_state") or {},
        "log": log,
        "_latencies": latencies,
    }


def aggregate(rows: list[dict]) -> dict:
    scored = [r for r in rows if not r["unavailable"]]
    lat = [x for r in rows for x in r["_latencies"]]
    reached = [r for r in scored if r["done_timing"]["goal_first_met_step"] is not None]
    lags = [r["done_timing"]["lag"] for r in reached if r["done_timing"]["lag"] is not None]
    n = len(scored) or 1
    return {
        "runs": len(rows), "scored": len(scored), "unavailable": len(rows) - len(scored),
        "strict": round(sum(bool(r["strict"]) for r in scored) / n, 4),
        "partial": round(sum(r["partial"] or 0 for r in scored) / n, 4),
        "no_progress_loop": sum(r["no_progress_loop"] for r in scored),
        "steps_mean": round(sum(r["steps"] for r in scored) / n, 2),
        "latency_s": {"p50": pct(lat, .5), "p95": pct(lat, .95), "n": len(lat)},
        "done": {
            "goal_reached": len(reached),
            # DONE while the goal still held: a run that reached the goal, undid it and then stopped is a false DONE.
            "done_after_reached": sum(r["done_timing"]["done_step"] != "never"
                                      and r["done_timing"].get("goal_met_at_done") for r in reached),
            "never_done_after_reached": sum(r["done_timing"]["done_step"] == "never" for r in reached),
            "false_done": sum(r["done_timing"]["false_done"] for r in scored),
            "lag_mean": round(sum(lags) / len(lags), 2) if lags else None,
            "lag_median": statistics.median(lags) if lags else None,
            "stops_by_model": sum(r["done_timing"].get("stop_by") == "model" for r in scored),
            "stops_by_check": sum(r["done_timing"].get("stop_by") == "check" for r in scored),
            "wasted_after_goal": sum(r["done_timing"].get("wasted_after_goal") or 0 for r in reached),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deskmind-bench run", description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", required=True, dest="task_set")
    ap.add_argument("--url", help="/v1/systemone base URL of the checkpoint under test (required unless --hosted)")
    ap.add_argument("--label", required=True, help="checkpoint name for the summary")
    ap.add_argument("--model", default=None, help="model name sent in the request (default: --label)")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--projection", choices=["on", "off"], default="on",
                    help="desktop projection layer; only the peekaboo driver has one")
    ap.add_argument("--driver", default=None, help="default: mock for smoke, peekaboo otherwise")
    ap.add_argument("--task", action="append", help="only these task ids")
    ap.add_argument("--completion-check", type=float, default=0.0,
                    help="arm C: end the run when P(goal complete) >= this after a step (0 = off)")
    ap.add_argument("--allow-remote", action="store_true", help="permit a non-local --url (may cost money)")
    ap.add_argument("--hosted", action="store_true",
                    help="a hosted System One reference (SYSTEMONE_BASE_URL and SYSTEMONE_API_KEY from the environment); "
                         "--url is ignored and the endpoint is not written to the report")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.hosted:
        if not (os.environ.get("SYSTEMONE_API_KEY") and os.environ.get("SYSTEMONE_BASE_URL")):
            raise SystemExit("--hosted needs SYSTEMONE_BASE_URL and SYSTEMONE_API_KEY in the environment")
        args.url, args.allow_remote = os.environ.get("SYSTEMONE_BASE_URL", ""), True

    if not args.url:
        raise SystemExit("--url is required (or --hosted)")
    if urlparse(args.url).hostname not in LOCAL_HOSTS and not args.allow_remote:
        raise SystemExit(f"{args.url} is not local; pass --allow-remote if spending on it is intended")
    driver = args.driver or ("mock" if args.task_set == "smoke" else "peekaboo")
    if not args.hosted:
        os.environ.pop("SYSTEMONE_API_KEY", None)
    os.environ["HANDS_TRACK_GOAL"] = "1"
    os.environ["HANDS_COMPLETION_CHECK"] = str(args.completion_check or 0)
    os.environ["HANDS_PROJECTION"] = "1" if args.projection == "on" else "0"
    os.environ.setdefault("HANDS_PEEKABOO_TRANSPORT", "mcp")

    try:
        from deskmind_hands.cli import main as cli_main
    except ImportError as exc:
        raise SystemExit("executing runs needs deskmind-hands (pip install 'deskmind-bench[run]'); "
                         "scoring finished runs does not: deskmind-bench score") from exc
    # The suite is this checkout's, whichever checkout deskmind-hands runs from.
    os.environ["DESKMIND_TASKS_DIR"] = str(REPO / "tasks")
    os.environ["DESKMIND_FIXTURES_DIR"] = str(REPO / "fixtures")
    report_path = Path(tempfile.mkstemp(suffix=".json", prefix="hands-bench-")[1])
    argv = ["deskmind-hands", "run", "--set", args.task_set, "--driver", driver, "--adapter", "systemone",
            "--model", args.model or args.label, "--systemone-url", args.url, "--repeats", str(args.repeats),
            "--system", args.label, "--no-screenshots", "--report", str(report_path)]
    for t in args.task or []:
        argv += ["--task", t]
    sys.argv = argv
    try:
        cli_main()
    except SystemExit:
        pass
    report = json.loads(report_path.read_text())
    runs_dir = Path(report["runs_dir"])
    rows = [run_summary(r, runs_dir) for r in report["runs"]]

    per_task = {}
    for r in rows:
        per_task.setdefault(r["task_id"], []).append(r)
    summary = {
        "label": args.label, "url": "hosted" if args.hosted else args.url, "task_set": args.task_set, "driver": driver,
        "projection": args.projection if driver == "peekaboo" else "n/a",
        "repeats": args.repeats, "completion_check": args.completion_check or None,
        "suite_version": f"{args.task_set}-v{SUITE_VERSION}", "suite_hash": suite_hash(args.task_set),
        "tasks": sorted(per_task),
        "aggregate": aggregate(rows),
        "per_task": {k: aggregate(v) for k, v in sorted(per_task.items())},
        "runs": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
        "runs_dir": str(runs_dir),
    }
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    a = summary["aggregate"]
    print(f"\n{args.label} on {args.task_set} ({summary['suite_version']} {summary['suite_hash']}, "
          f"projection {summary['projection']}): strict {a['strict']:.0%}  partial {a['partial']:.2f}  "
          f"loops {a['no_progress_loop']}  DONE after goal {a['done']['done_after_reached']}/"
          f"{a['done']['goal_reached']}  false DONE {a['done']['false_done']}  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
