# Scoring · [中文](scoring.zh-CN.md)

## Two numbers, kept apart

- **strict**: every checkpoint passes, every guard still holds, no forbid clause fired, every sentinel file is
  byte-identical. This is the headline number.
- **partial**: the weighted share of checkpoints passed, zero if a critical checkpoint failed. Reported next to strict,
  never instead of it. A run that broke something keeps its partial credit *and* its violation.

Runs that failed for reasons outside the planner (`environment`, `provider_unavailable`, `harness_bug`) are reported
as availability and excluded from both numbers. A grader that throws is a harness bug, never a silent zero.

## What a summary contains

`deskmind-bench run` and `deskmind-bench score` write the same shape:

| field | meaning |
|---|---|
| `aggregate.strict`, `aggregate.partial` | over scored runs |
| `aggregate.unavailable` | runs excluded as not the planner's fault |
| `aggregate.done.false_done` | DONE declared while the grader disagreed |
| `aggregate.done.done_after_reached`, `lag_mean` | the goal was met at step *k*; DONE came at step *k + lag* (or never) |
| `aggregate.no_progress_loop` | runs stopped for repeating the same state |
| `aggregate.latency_s` | p50 / p95 of the planner's time per decision |
| `per_task` | the same aggregate per task: read this first |
| `runs[].log` | per step: operation, target label, ok / error, whether the screen changed |
| `suite_hash`, `suite_version` | what was asked and graded; which harness produced the runs |

DONE timing needs the harness to grade the workspace after every action (`deskmind-bench run` switches this on).

## Scoring finished runs without the driver

`deskmind-bench score RUNS...` accepts run directories, a directory of runs, or a DeskMind Hands report file. For each
run it reads `run.json` (final state, metrics), `trace.jsonl` and the workspace `ws/`, unpacks nothing and imports no
driver. Sentinel digests are taken from the pristine fixture, as the harness takes them right after the reset. The
harness's own grade is kept as `recorded_grade`; `regrade.strict_changed` lists runs where the two disagree, which
means the tasks or graders differ from the ones the runs were made with.

Two limits: the clipboard is not recorded, so a task that checks it keeps its recorded grade (the diag suite has
none); and a run directory does not name its harness version, so pass `--suite-version` to label the summary. The
manifest's harness commit is listed in `harness_commits`.

## Comparing configs

- Same `suite_hash` **and** same harness version, or the numbers are not comparable.
- Report per-task passes (`deskmind-bench table`). With 13 tasks × 3 runs, most tasks pass 3/3 or 0/3; the effective
  sample is closer to 13 than to 39.
- For an interval, resample tasks with their repeats (a clustered bootstrap), not runs. Treating 39 runs as
  independent makes the interval too narrow, because repeats of one task are strongly correlated.
