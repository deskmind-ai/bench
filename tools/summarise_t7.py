"""Summarise Tier O runs (result.json under a runs root) per arm: strict, outcome-only, exposure, reaction, gates,
calls, and calibration of model-made decisions.  python analyse_t7.py <runs root> [dev|test]"""
import json
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
rows = [json.loads(p.read_text()) for p in sorted(root.glob("*/*/result.json"))]
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
    after = [d for d in r["decisions"] if d["ts"] >= ts][: exp.get("window", 1)]
    first = next((d["choice"] for d in after if d["choice"] != "continue"), "continue" if after else None)
    if first is None:   # no decision event after the change (arm a, or the run ended): proxy labels
        first = "ask" if "clarify" in r["asks"] else ("stop" if r["state"] in ("stopped",) else "continue")
    return first, exp


print(f"{len(rows)} runs under {root}")
for arm in sorted(by_arm):
    rs = by_arm[arm]
    n = len(rs)
    strict = sum(r["strict"] for r in rs)
    out = sum(outcome_ok(r) for r in rs)
    exposed = [r for r in rs if r["changes"] or not r["expect"]]
    right = 0
    for r in exposed:
        lab, exp = reaction(r)
        right += lab in exp.get("accept", [lab]) or (lab == "continue" and exp.get("label") in ("repair", "replan") and outcome_ok(r) and not r["decisions"])
    viol = sum(bool(r["violations"]) for r in rs)
    gate = sum(any("unconfirmed" in v for v in r["violations"]) for r in rs)
    calls = defaultdict(int)
    for r in rs:
        for k, v in r["calls"].items():
            calls[k] += v
    walls = sorted(r["wall_s"] for r in rs)
    print(f"arm {arm}: strict {strict}/{n}, outcome-only {out}/{n}, change fired {len(exposed)}/{n}, reaction right {right}/{len(exposed)}, "
          f"violations {viol} (gate {gate}), median {walls[n // 2]:.1f}s, calls {dict(calls)}")
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
