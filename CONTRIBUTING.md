# Contributing to DeskMind Bench · [中文](CONTRIBUTING.zh-CN.md)

Thanks for helping. DeskMind Bench is the scorer of record, so every change is judged the same way: after it, does a
number from this repository still mean exactly what it says? The org-wide guidelines
([deskmind-ai/.github](https://github.com/deskmind-ai/.github)) apply here too, including the
[code of conduct](https://github.com/deskmind-ai/.github/blob/main/CODE_OF_CONDUCT.md).

The two most useful contributions are a new task and a results submission. Both have an issue form.

## Set up

```bash
git clone https://github.com/deskmind-ai/bench && cd bench
python -m venv .venv && . .venv/bin/activate
pip install -e .

python -m unittest discover -s tests -v   # must pass before you open a PR
deskmind-bench verify                     # every diag task: oracle passes, doing nothing fails
deskmind-bench hash                       # must print 5eec62a0c662 on an unchanged checkout
```

- Scoring, verifying and hashing need only Python 3.11+ and PyYAML: no Mac, no driver, no model. Most issues can be
  done on Linux.
- Executing runs needs a Mac with [DeskMind Hands](https://github.com/deskmind-ai/hands) (`pip install -e ".[run]"`),
  Peekaboo and its permissions. See the README.

## How to add a task

New tasks go into their own set, `tasks/proposals/`, never into `tasks/diag/`. Any change to a diag task, a fixture
it uses or a grader changes the suite hash, and every published number stops being comparable. Proposals are promoted
into a new suite version by the maintainers, all at once, with new reference runs.

Open a **New task proposal** issue first. It asks what the task tests and why a shortcut cannot solve it, which is
where most proposals are improved.

**1. The fixture.** A directory under `fixtures/<name>/` that is unpacked into a fresh sandbox folder (`$WS`) before
every run. Keep it small and plain text. Include `keep/reference.txt` as a sentinel, as every diag fixture does.

**2. The task file**, `tasks/proposals/Pnn-<app>-<what>.yaml`. The schema is `deskmind_bench/task.py`:

| field | what it is |
|---|---|
| `id`, `title`, `goal` | unique id (the file name without `.yaml`); a short title; the instruction the agent gets |
| `app`, `surface`, `tags` | the bundle id observed first (`com.apple.finder`, never a display name); a coarse area; free tags |
| `fixture` | the directory under `fixtures/` |
| `stage`, `reset_apps` | shell commands run before the agent starts (open the documents the premise needs); apps whose windows are closed first |
| `budget` | `max_actions`, `wall_clock_s`, `max_dialogue_turns` |
| `sentinels` | files that must be byte-identical at the end; every path starts with `$WS/` |
| `grade.checkpoints` | `name`, `check`, optional `weight`, `critical` (zeroes partial credit on failure), `process` (about the route, not the end state) |
| `grade.guards` | must still hold at the end; gate strict success but earn nothing |
| `grade.forbid` | side effects that must not happen |
| `user_script`, `inject` | replies to the agent's questions; events fired from outside (for example `cancel` at action *n*) |
| `oracle_effect` | shell commands, run inside `$WS`, that put the workspace straight into the correct end state |

Checks are the predicates in `deskmind_bench/graders/primitives.py` (`file_text_equals`, `dir_manifest`,
`file_count`, `run_field`, ...), combined with `all_of`, `any_of` and `not`. Avoid `clipboard_equals`: the clipboard is
not recorded, so such a task cannot be rescored from disk. If a task needs a check that does not exist, propose the
predicate in its own PR first.

**3. The oracle and the null control.** `oracle_effect` proves the task can be solved and that the grader accepts a
correct outcome. The null control is the untouched fixture, graded as a run that declared DONE at once. `verify` runs
both, and both must hold:

```bash
deskmind-bench verify --set proposals
```

- The oracle reaches **strict success**: every outcome checkpoint passes, no guard breaks, no forbid clause fires, the
  sentinels are untouched. Process checkpoints are skipped for the oracle and enforced for every real run.
- The null control scores **0**: not strict, and partial credit exactly 0. `allow_vacuous` exists in the schema, but a
  proposal that needs it will not be accepted.

A task that fails either check is broken, not hard. `deskmind-bench hash` must still print `5eec62a0c662`.

**The sandbox rule.** A task touches only its own workspace. `oracle_effect` and `stage` use paths relative to `$WS`,
never `~`, an absolute path or the network. A task may not depend on anything in the user's home folder, accounts or
real documents, and it must not need the Trash, the Desktop or iCloud.

**What makes a good task:** it isolates one thing agents get wrong; it cannot be passed by a shortcut (doing nothing,
doing everything, writing a guessable constant, or editing the wrong one of two look-alike files); the goal names what
it wants unambiguously, unless ambiguity is the point; and its grader checks the outcome, not a particular route.

## How to submit results

Open a **Results submission** issue, then a PR that adds two files under `results/community/<suite_version>/`:

- `<label>.json`: the entry described below;
- `<label>.summary.json`: the summary `deskmind-bench run` wrote (or `deskmind-bench score`, if you regraded runs).

```bash
deskmind-bench run --set diag --repeats 3 --url http://127.0.0.1:8793 --label my-planner --out my-planner.summary.json
deskmind-bench table my-planner.summary.json
```

**The rules.**

- **Same suite, same harness.** `suite_hash` must equal `deskmind-bench hash` and the hash listed for your
  `suite_version` in `results/versions.json`. Run on the version marked `current`; a `frozen` one takes no new numbers.
  Results on different harness versions are not comparable, even with the same suite hash, and are listed in separate
  tables.
- **Name the harness exactly.** `hands_commit` is the full commit of deskmind-ai/hands you ran, with no local changes.
  A modified harness is a different harness: say what you changed, and the entry is listed apart.
- **n ≥ 3.** At least three runs of every task in the suite, all of them. Report what happened, not the best round.
- **Per-task counts.** Passes, scored runs and env errors for every task, adding up to the totals.
- **Env errors apart.** Runs that ended in `environment`, `provider_unavailable` or `harness_bug` are excluded from
  strict and reported in `env_errors`. You may rerun those runs, never runs the planner failed; say so in `rounds` and
  `note`.
- **Say how the model was served.** Weights, inference stack and version, precision or quantisation, hardware,
  local or remote. A hosted API counts as remote and needs `--allow-remote` or `--hosted`; say which.
- Keep the run directories. We may ask for them to regrade with `deskmind-bench score`.

**The entry** (`<label>.json`) extends one element of `configs` in `results/reference.json` with the fields a third
party has to state:

| field | type | meaning |
|---|---|---|
| `schema` | string | `"deskmind-bench-results/1"` |
| `suite`, `suite_version`, `suite_hash` | string | `"diag"`, `"diag-v21"`, `"5eec62a0c662"` |
| `hands_commit` | string | full commit of deskmind-ai/hands used for the runs |
| `label`, `system` | string | short name; one line describing the system and its revision |
| `runs_on` | string | `"local, <chip / GPU>"` or `"cloud"` |
| `projection` | string | `"on"` or `"off"` |
| `repeats_per_task`, `rounds` | int | ≥ 3; how many separate sessions the runs came from |
| `runs`, `scored`, `env_errors`, `passed` | int | all runs; runs scored; runs excluded; strict passes. `runs = scored + env_errors` |
| `strict`, `partial` | float | `passed / scored` rounded to 4 places; mean partial credit over scored runs |
| `false_done`, `no_progress_loops` | int | from the summary's `aggregate` |
| `step_latency_s` | object or null | `{"p50": s, "p95": s}`, planner time per decision; null if not pooled |
| `per_task` | object | `{task_id: {"passed", "scored", "env_errors"}}` for every task in the suite |
| `serving` | object | `{"weights", "stack", "precision", "hardware", "endpoint"}`: `weights` is a link or `"closed"`, `endpoint` is `"local"` or `"remote"` |
| `compute` | string | wall-clock time of the runs, and cost if any |
| `submitted_by`, `date` | string | GitHub handle; ISO date of the runs |
| `note` | string | optional: anything a reader needs to interpret the numbers |

## Pull requests

- **One change per PR,** with a short description of what changed and how you checked it.
- **Scoring changes need evidence.** A change to a grader, the scorer or the runner comes with `deskmind-bench score`
  output on existing runs before and after, and says which numbers move. If the suite hash changes, the PR says why.
- **Style.** Match the surrounding code: small functions, comments that explain why, no new dependencies in the scorer
  (Python and PyYAML only).
- **Checklist:**
  - [ ] `python -m unittest discover -s tests` and `deskmind-bench verify --set <every set you touched>` pass;
  - [ ] `deskmind-bench hash` still prints `5eec62a0c662`, or the PR explains the change;
  - [ ] tasks and fixtures stay inside `$WS` and contain no real personal data;
  - [ ] docs updated in English and 中文 (`docs/*.md` and `docs/*.zh-CN.md`).

## Reporting problems

- **A task or grader bug** (a correct run fails, or a wrong one passes): give the task id, the suite version, and the
  run's `run.json` and `trace.jsonl` with anything personal removed.
- **Security issues:** don't open a public issue. See
  [SECURITY.md](https://github.com/deskmind-ai/.github/blob/main/SECURITY.md).

By contributing you agree that your contribution is licensed under Apache-2.0, the licence of this repository.
