"""deskmind-bench: run, score and check the DeskMind Bench suites.

    deskmind-bench verify  [--set diag]                       tasks self-check, no driver (oracle passes, null fails)
    deskmind-bench hash    [--set diag]                       the suite hash of this checkout
    deskmind-bench versions                                   harness versions and suite hashes of the reference results
    deskmind-bench score   RUNS... [--set diag] [--out F]     regrade finished runs from disk, no driver
    deskmind-bench table   SUMMARY.json...                    per-task passes as a markdown table
    deskmind-bench run     --set diag --url ... --label ...   execute runs (needs deskmind-hands and a Mac)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .suite import REPO


def _versions() -> int:
    data = json.loads((REPO / "results" / "versions.json").read_text(encoding="utf-8"))
    print(f"{'suite version':<14} {'suite hash':<13} {'harness commit':<15} status")
    for v in data["versions"]:
        print(f"{v['suite_version']:<14} {v['suite_hash']:<13} {v['hands_commit']:<15} {v.get('status', '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["run"]:
        from .bench import main as run_main
        return run_main(argv[1:])

    ap = argparse.ArgumentParser(prog="deskmind-bench", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="task self-check without a driver")
    v.add_argument("--set", default="diag", dest="task_set")
    h = sub.add_parser("hash", help="print the suite hash")
    h.add_argument("--set", default="diag", dest="task_set")
    sub.add_parser("versions", help="list harness versions and suite hashes")
    s = sub.add_parser("score", help="regrade finished runs from disk")
    s.add_argument("runs", nargs="+", type=Path, help="run directories, directories of runs, or hands report files")
    s.add_argument("--set", default="diag", dest="task_set")
    s.add_argument("--label", default="rescored")
    s.add_argument("--suite-version", help="the harness version the runs were made with, e.g. diag-v21 (see versions)")
    s.add_argument("--out", type=Path)
    t = sub.add_parser("table", help="per-task passes from summary files")
    t.add_argument("summaries", nargs="+", type=Path)
    sub.add_parser("run", help="execute runs through deskmind-hands (see deskmind-bench run --help)")
    args = ap.parse_args(argv)

    if args.cmd == "verify":
        from .verify import verify
        return verify(args.task_set)
    if args.cmd == "hash":
        from .suite import suite_hash
        print(suite_hash(args.task_set))
        return 0
    if args.cmd == "versions":
        return _versions()
    if args.cmd == "score":
        from .scoring import score
        summary = score(args.runs, args.task_set, label=args.label, suite_version=args.suite_version)
        a = summary["aggregate"]
        text = json.dumps(summary, ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        made_with = summary["suite_version"] or ("harness " + ", ".join(c[:7] for c in summary["harness_commits"])
                                                 if summary["harness_commits"] else "harness version unknown")
        print(f"{args.label} on {args.task_set} (suite {summary['suite_hash']}, {made_with}): "
              f"strict {round(a['strict'] * a['scored'])}/{a['scored']} ({a['strict']:.0%})  "
              f"env errors {a['unavailable']}  partial {a['partial']:.2f}  false DONE {a['done']['false_done']}  "
              f"regraded {summary['regrade']['regraded']}/{summary['regrade']['runs']}, "
              f"strict changed on {len(summary['regrade']['strict_changed'])}"
              + (f"  -> {args.out}" if args.out else ""))
        return 0
    if args.cmd == "table":
        from .scoring import pass_table
        print(pass_table([json.loads(p.read_text(encoding="utf-8")) for p in args.summaries]))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
