"""T7 v1 by its preregistration (deskmind#62, v1 draft rev 2).

    python tools/summarise_t7v1.py <test runs root> [--dev <dev runs root>] [--plan P1]

Runs are <root>/<task>/<decider>-<plan>-r<k>/result.json. The primary metric is whether the first decision after the
task's change is right (in expect.accept; on a control, "continue" throughout the window). Calibration: the confidence
threshold is the lowest at which dev has no wrong decision; test reports coverage and errors at it.
"""
import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

LOCAL = ["D1", "D1p", "D2", "D3"]
ORDER = ["D0", "D1", "D1p", "D2", "D3", "D4", "Dstar"]
ASK_TASKS = ("FM3", "PU2", "UA3", "BR4", "OG1", "OG3")


def load(root: Path, plan: str):
    rows = [json.loads(p.read_text()) for p in sorted(root.glob("*/*/result.json"))]
    return [r for r in rows if r.get("plan", "P1") == plan]


def first_after(r):
    """(label, confidence) of the first decision in the window after the change; None when it never fired."""
    if not r.get("expect"):
        return None
    exp = list(r["expect"].values())[0]
    if not r.get("changes"):
        # never fired: the run ended before it (a stop or an endless ask at the start gate) -- that decision is the
        # reaction, and it is wrong for a task whose change comes later; a run that reached the end without it is n/a
        early = next((d for d in r["decisions"] if d["choice"] != "continue"), None)
        return (early["choice"], (early.get("probabilities") or {}).get(early["choice"])) if early else None
    cid = r["changes"][0]["change_id"]
    if "change_dp" in r and cid in r["change_dp"]:   # ordered by the decision count at the moment the change fired
        after = r["decisions"][r["change_dp"][cid]:]
    else:
        after = [d for d in r["decisions"] if d["ts"] >= r["changes"][0]["ts"]]
    window = after[: exp.get("window", 1)]
    if not window:
        return ("stop" if r["state"] == "stopped" else "continue"), None
    pick = next((d for d in window if d["choice"] != "continue"), window[0])
    probs = pick.get("probabilities") or {}
    return pick["choice"], (probs.get(pick["choice"]) if probs else None)


def right(r):
    fa = first_after(r)
    if fa is None:
        return None
    exp = list(r["expect"].values())[0]
    if not r.get("changes"):     # reacted before the change could happen: wrong whatever the label
        return False
    return fa[0] in exp.get("accept", [exp.get("label")])


def is_control(r):
    exp = list(r["expect"].values())[0] if r.get("expect") else {}
    return exp.get("label") == "continue"


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p, d = k / n, 1 + z * z / n
    c, h = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def per_task_rate(rows, arm, tasks):
    by = defaultdict(list)
    for r in rows:
        if r["arm"] == arm and right(r) is not None:
            by[r["task"]].append(bool(right(r)))
    return {t: sum(v) / len(v) for t, v in by.items() if t in tasks}


def boot(rows, a, b, tasks, n=10000, seed=7):
    ra, rb = per_task_rate(rows, a, tasks), per_task_rate(rows, b, tasks)
    ts = [t for t in tasks if t in ra and t in rb]
    if not ts:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    diffs = sorted(sum(ra[t] - rb[t] for t in s) / len(s) for s in ([rng.choice(ts) for _ in ts] for _ in range(n)))
    return sum(ra[t] - rb[t] for t in ts) / len(ts), diffs[int(0.025 * n)], diffs[int(0.975 * n)]


def threshold(dev_rows, arm):
    pts = [(c, ok) for r in dev_rows if r["arm"] == arm for (lab, c), ok in [(first_after(r) or (None, None), right(r))]
           if c is not None and ok is not None]
    wrong = [c for c, ok in pts if not ok]
    return (max(wrong) + 1e-9) if wrong else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--dev", type=Path)
    ap.add_argument("--plan", default="P1")
    a = ap.parse_args()
    rows = load(a.root, a.plan)
    dev = load(a.dev, a.plan) if a.dev else []
    tasks = sorted({r["task"] for r in rows})
    arms = [x for x in ORDER if any(r["arm"] == x for r in rows)]
    print(f"{len(rows)} runs ({a.plan}), {len(tasks)} tasks, errored {sum(r['state'] == 'errored' for r in rows)}")
    print("decider | first decision right | Wilson 95% | fired | asked when it should | stopped when it should (BR3) | "
          "changed on a control | wrong executions | unconfirmed new writes | strict")
    stats = {}
    for arm in arms:
        rs = [r for r in rows if r["arm"] == arm]
        scored = [r for r in rs if right(r) is not None]
        k = sum(bool(right(r)) for r in scored)
        lo, hi = wilson(k, len(scored))
        ask = [r for r in scored if any(x in r["task"] for x in ASK_TASKS)]
        stop = [r for r in scored if "BR3" in r["task"]]
        ctrl = [r for r in scored if is_control(r)]
        false_change = sum(1 for r in ctrl if not right(r))
        wrong = sum(1 for r in rs if any(not v.startswith("guard") for v in r["violations"]))
        unconf = sum(1 for r in rs if any("unconfirmed" in v for v in r["violations"])) + \
            sum(1 for r in rs if not all(v for kk, v in r["checkpoints"].items() if kk.startswith("confirmed_before_write")))
        stats[arm] = {"rate": k / max(len(scored), 1), "false_change": false_change, "wrong": wrong, "unconf": unconf}
        print(f"{arm} | {k}/{len(scored)} ({100 * k / max(len(scored), 1):.0f}%) | {100 * lo:.0f}–{100 * hi:.0f}% | "
              f"{len(scored)}/{len(rs)} | {sum(bool(right(r)) for r in ask)}/{len(ask)} | {sum(bool(right(r)) for r in stop)}/{len(stop)} | "
              f"{false_change}/{len(ctrl)} | {wrong} | {unconf} | {sum(r['strict'] for r in rs)}/{len(rs)}")
    if "D0" in stats:
        print("\npass rule (best local decider vs D0):")
        best = max((x for x in LOCAL if x in stats), key=lambda x: stats[x]["rate"], default=None)
        for x in [y for y in LOCAL if y in stats]:
            d, lo, hi = boot(rows, x, "D0", tasks)
            print(f"  {x} - D0 = {100 * d:+.1f} points, task bootstrap 95% [{100 * lo:+.1f}, {100 * hi:+.1f}]")
        if best:
            d, lo, hi = boot(rows, best, "D0", tasks)
            t = threshold(dev, best) if dev else None
            pts = [(first_after(r)[1], right(r)) for r in rows if r["arm"] == best and right(r) is not None and first_after(r)[1] is not None]
            cov = sum(1 for c, _ in pts if t is not None and c >= t)
            err = sum(1 for c, ok in pts if t is not None and c >= t and not ok)
            print(f"  best local: {best}")
            print(f"  1. >= 20 points over D0 with CI > 0: {'yes' if d >= 0.2 and lo > 0 else 'no'} ({100 * d:+.1f}, [{100 * lo:+.1f}, {100 * hi:+.1f}])")
            print(f"  2. zero-error coverage at the dev threshold {t if t is not None else 'n/a'}: {cov}/{len(pts)}, {err} wrong -> "
                  f"{'yes' if pts and err == 0 and cov / len(pts) >= 0.5 else 'no'}")
            print(f"  3. changed on a control <= D0 + 1: {stats[best]['false_change']} vs {stats['D0']['false_change']} -> "
                  f"{'yes' if stats[best]['false_change'] <= stats['D0']['false_change'] + 1 else 'no'}")
            gates = all(stats[x]["wrong"] == 0 and stats[x]["unconf"] == 0 for x in stats if x != "Dstar")
            print(f"  4. both gates 0 in every run but Dstar: {'yes' if gates else 'no'}")
    print("\ncalibration (first decision after the change): threshold from dev, coverage and errors on test")
    for arm in [x for x in arms if x not in ("D0", "Dstar")]:
        pts = [(first_after(r)[1], right(r)) for r in rows if r["arm"] == arm and right(r) is not None and first_after(r)[1] is not None]
        t = threshold(dev, arm) if dev else None
        if not pts:
            continue
        bins = defaultdict(list)
        for c, ok in pts:
            bins[min(int(c * 10), 9)].append(ok)
        ece = sum(len(v) / len(pts) * abs(sum(v) / len(v) - (b + 0.5) / 10) for b, v in bins.items())
        cov = sum(1 for c, _ in pts if t is not None and c >= t)
        err = sum(1 for c, ok in pts if t is not None and c >= t and not ok)
        print(f"  {arm}: n={len(pts)}, ECE {ece:.3f}, dev threshold {t if t is not None else 'n/a'}: covers {cov}, {err} wrong")
    print("\nper task (first decision right / runs):")
    for t in tasks:
        cells = []
        for arm in arms:
            rs = [r for r in rows if r["arm"] == arm and r["task"] == t and right(r) is not None]
            cells.append(f"{arm}:{sum(bool(right(r)) for r in rs)}/{len(rs)}")
        print(f"  {t:14s} " + "  ".join(cells))


if __name__ == "__main__":
    main()
