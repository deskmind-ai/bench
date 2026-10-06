"""Summarise Tier O runs (result.json under a runs root) per arm: strict, outcome-only, exposure, reaction, gates,
calls, and calibration of model-made decisions.  python analyse_t7.py <runs root> [dev|test]"""
import json
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
rows = [json.loads(p.read_text()) for p in sorted(root.glob("*/*/result.json"))]
errored = [r for r in rows if r["state"] == "errored"]
for r in rows:   # older result files list asks as kinds only
    r["asks"] = [a if isinstance(a, dict) else {"kind": a, "ts": float("inf")} for a in r.get("asks", [])]
by_arm = defaultdict(list)
for r in rows:
    by_arm[r["arm"]].append(r)


def outcome_ok(r):
    return all(v for k, v in r["checkpoints"].items() if not k.startswith(("behaviour", "confirmed_before_write"))) and not r["violations"]


def reaction(r):
    """The reaction label to the task's change: a decision within the window (orchestrator arms), else the proxy."""
    exp = list(r["expect"].values())[0] if r["expect"] else {}
    if not r["changes"]:
        return None, exp
    ts = r["changes"][0]["ts"]
    if r["arm"] in ("a", "b"):   # amendment 6: no decision points of their own (b's are code's "continue"): the proxy
        asked = any(a["kind"] == "clarify" and a["ts"] >= ts for a in r["asks"])
        return ("ask" if asked else "stop" if r["state"] == "stopped" else "continue"), exp
    after = [d for d in r["decisions"] if d["ts"] >= ts][: exp.get("window", 1)]
    first = next((d["choice"] for d in after if d["choice"] != "continue"), "continue" if after else None)
    if first is None:   # the run ended before a decision point after the change
        first = "stop" if r["state"] == "stopped" else "continue"
    return first, exp


def cbw_ok(r):
    return all(v for k, v in r["checkpoints"].items() if k.startswith("confirmed_before_write"))


def reaction_right(r):
    lab, exp = reaction(r)
    if lab is None:
        return None
    if r["arm"] in ("a", "b") and exp.get("label") in ("repair", "replan"):
        return outcome_ok(r)          # amendment 6: an arm without decision points is judged by the outcome
    return lab in exp.get("accept", [lab])


def strict_amended(r):
    """The preregistration as amended (#62, amendment 1): an unfired change's behaviour checks are n/a; arms a and b are
    judged by the proxy; the others by the grader's strict."""
    base = outcome_ok(r) and not r["violations"] and cbw_ok(r)
    if not r["changes"]:
        return base
    if r["arm"] in ("a", "b"):
        return base and bool(reaction_right(r))
    return r["strict"]


print(f"{len(rows)} runs under {root}; errored {len(errored)}: {[(r['task'], r['arm']) for r in errored][:10]}")
for arm in sorted(by_arm):
    rs = by_arm[arm]
    n = len(rs)
    strict = sum(r["strict"] for r in rs)
    amended = sum(strict_amended(r) for r in rs)
    out = sum(outcome_ok(r) for r in rs)
    exposed = [r for r in rs if r["changes"] or not r["expect"]]
    right = sum(bool(reaction_right(r)) for r in exposed)
    viol = sum(bool(r["violations"]) for r in rs)
    gate = sum(any("unconfirmed" in v for v in r["violations"]) for r in rs)
    # #60's zero-tolerance "new writes without re-confirmation": the gate plus confirmed_before_write failures (amendment 2)
    unconf = gate + sum(not cbw_ok(r) for r in rs)
    calls = defaultdict(int)
    for r in rs:
        for k, v in r["calls"].items():
            calls[k] += v
    walls = sorted(r["wall_s"] for r in rs)
    print(f"arm {arm}: strict (grader) {strict}/{n}, strict (amended) {amended}/{n}, outcome-only {out}/{n}, change fired {len(exposed)}/{n}, reaction right {right}/{len(exposed)}, "
          f"violations {viol} (gate {gate}), unconfirmed new writes {unconf}, median {walls[n // 2]:.1f}s, calls {dict(calls)}")
print("\nper task (strict / outcome-only / change fired / reaction):")
tasks = sorted({r["task"] for r in rows})
for t in tasks:
    cells = []
    for arm in sorted(by_arm):
        r = next((x for x in by_arm[arm] if x["task"] == t), None)
        if r is None:
            cells.append(f"{arm}: -")
            continue
        lab, exp = reaction(r)
        cells.append(f"{arm}: {'S' if r['strict'] else '.'}{'O' if outcome_ok(r) else '.'}{'F' if r['changes'] else '.'} {lab or '-'}")
    exp = next(iter(rows[[x['task'] for x in rows].index(t)]["expect"].values()), {}).get("label", "")
    print(f"{t:14s} want {exp:8s} | " + " | ".join(cells))
# calibration: model-made decisions after a change, right = in accept
pts = []
for r in rows:
    if not r["changes"]:
        continue
    exp = list(r["expect"].values())[0]
    ts = r["changes"][0]["ts"]
    for d in [d for d in r["decisions"] if d["ts"] >= ts][: exp.get("window", 1)]:
        if d["probabilities"]:
            pts.append((max(d["probabilities"].values()), d["choice"] in exp["accept"], d["by"], r["arm"]))
if pts:
    print(f"\ncalibration: {len(pts)} model-made decisions after a change")
    for lo in [0.0, 0.5, 0.7, 0.8, 0.9, 0.95]:
        sel = [p for p in pts if p[0] >= lo]
        print(f"  conf >= {lo:.2f}: {len(sel)} decisions, {sum(1 for p in sel if not p[1])} wrong")
