<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/banner-dark.svg">
    <img src="assets/brand/banner-light.svg" alt="DeskMind 得心 — 得心，应手。" width="720">
  </picture>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/lockup-dark.svg">
    <img src="assets/brand/lockup-light.svg" height="40" alt="DeskMind">
  </picture><br>
  <b>DeskMind Bench</b> · Sandbox macOS desktop tasks, their graders, and reference runs.<br>
  <a href="README.zh-CN.md">中文</a> · <a href="docs/tasks.md">Tasks</a> · <a href="docs/scoring.md">Scoring</a> ·
  <a href="results/reference.md">Results</a> · <a href="results/versions.md">Versions</a>
</p>

---

**DeskMind · 得心** — *得心，应手。* (from 得心应手: what the mind decides, the hand carries out) is a family of
open-source projects that let an agent **see** your screen, **decide** the next step, and **act** on the real desktop,
all locally.

This repository is the **Bench**: the task suite our desktop numbers are measured on, the graders that score it, and
the scorer of record. Every DeskMind result names a suite hash and a harness version from this repository.

| | Repository | Role |
|---|---|---|
| 👁 | [deskmind-ai/eyes](https://github.com/deskmind-ai/eyes) | find the target on a screenshot |
| 🧠 | [deskmind-ai/brain](https://github.com/deskmind-ai/brain) | decide the next step, with calibrated confidence |
| ✋ | [deskmind-ai/hands](https://github.com/deskmind-ai/hands) | drive the real macOS desktop |
| 📐 | **deskmind-ai/bench** | sandbox desktop tasks and graders to reproduce our numbers |

## What the diag suite tests

Thirteen tasks on the real Finder, TextEdit and Safari, each in a sandbox folder unpacked from a fixture. Each one
isolates one thing a desktop agent gets wrong ([docs/tasks.md](docs/tasks.md)):

- **Finder operations:** make a folder, move a file, navigate down two levels and back up, sort files into a new
  folder, rename several files in turn.
- **Editing text exactly:** change two fields and save; type Chinese with full-width punctuation character for
  character; find one line in a 60-line log that needs scrolling.
- **Crossing apps:** read a table in Safari and append it sorted to a CSV; copy values from one document to another.
- **Behaving well:** ask when the goal is ambiguous instead of guessing; edit only the named one of two near-identical
  documents; stop when cancelled halfway.

A run passes (**strict**) only if every checkpoint passes, no guard is broken, no forbidden side effect happened, and
the sentinel files are untouched. Partial credit is reported separately and never replaces strict.

## Run and score

Scoring needs only Python and PyYAML: no Mac, no driver, no model.

```bash
git clone https://github.com/deskmind-ai/bench && cd bench
pip install -e .

deskmind-bench verify                  # every task: its effect oracle passes, doing nothing fails
deskmind-bench hash                    # 5eec62a0c662 -- the suite hash of the reference results
deskmind-bench versions                # harness versions and their commits
deskmind-bench score path/to/runs/ --suite-version diag-v25 --out mine.json   # regrade finished runs from disk
deskmind-bench table mine.json         # per-task passes as a markdown table
```

`score` reads each run's workspace, record and trace as [DeskMind Hands](https://github.com/deskmind-ai/hands) writes
them, grades them again with this repository's graders, and reports strict and partial pass, false DONE, DONE timing
and step latency. It never imports the driver.

Executing runs needs a Mac with DeskMind Hands, Peekaboo and its permissions, and a planner behind `/v1/systemone`:

```bash
git clone https://github.com/deskmind-ai/hands ../hands   # next to this checkout, as hands expects bench
pip install -e ../hands -e ".[run]"    # adds deskmind-hands
deskmind-bench run --set diag --repeats 3 --url http://127.0.0.1:8793 --label my-planner --out my-planner.json
```

The runner refuses a non-local URL unless you pass `--allow-remote`, and removes a hosted API key from the
environment unless you ask for the hosted reference (`--hosted`).

## Reference results

Real macOS desktop, 13 tasks × 3 runs, projection layer on, strict pass. Full per-task tables:
[results/reference.md](results/reference.md) (and `reference.json`).

| harness | config | strict pass | false DONE | step p50 |
|---|---|---|---|---|
| v25 | DeskMind Brain router (0.8B → 4B), g18b, 8-bit, threshold 0.96 (current) | **39/39 (100%)** | 0 | 2.85 s¹ |
| v25 | DeskMind Brain router (0.8B → 4B), 4B g14, 8-bit | 36/39 (92%) | 0 | 0.57 s |
| v25 | DeskMind Brain router, 4B g17, 8-bit | 36/39 (92%) | 3 | n/a |
| v23 | DeskMind Brain router, 4B g14, 8-bit | **35/38 (92%)**, 1 env error | 0 | 0.59 s |
| v23 | Jev (TypeSafe AI, cloud reference) | 33/38 (87%), 1 env error | 2 | 0.36 s |
| v21 | DeskMind Brain router (0.8B → 4B), rev. v7b | **32/39 (82%)** | 2 | 3.3 s |
| v20 | Jev (TypeSafe AI, cloud reference) | 33/39 (85%) | 0 | 0.4 s |
| v20 | DeskMind Brain router, rev. v7 | 29/39 (74%) | 3 | 3.2 s |
| v19 | DeskMind Brain router, rev. v7 | 30/39 (77%) | 2 | 3.6 s |
| v19 | DeskMind Brain 4B, g11b | 27/39 (69%) | 3 | 3.4 s |
| v19 | DeskMind Brain 4B, g10b | 24/39 (62%) | 7 | – |
| v19 | Jev (TypeSafe AI, cloud reference) | 31/37 (84%), 2 env errors | 2 | 1.0 s |

¹ Run through the DeskMind app, whose step time includes the app's own checks and the second model on the steps it
reviews; the other rows ran from the command line. p95 9.82 s.

## Versions

The tasks, fixtures and graders are the same in all versions (suite hash `5eec62a0c662`). What changed is the
harness: how the desktop is shown to the planner and how actions are carried out.
[results/versions.md](results/versions.md) (and `versions.json`) lists what changed in each.

| suite version | hands commit | suite hash | status |
|---|---|---|---|
| diag-v19 | `3aee984` | `5eec62a0c662` | frozen |
| diag-v20 | `7934cfa` | `5eec62a0c662` | superseded |
| diag-v21 | `f1df118` | `5eec62a0c662` | frozen |
| diag-v22 | `1c3f47d` | `5eec62a0c662` | frozen |
| diag-v23 | `713961b` | `5eec62a0c662` | frozen |
| diag-v24 | `4d12033` | `5eec62a0c662` | frozen |
| diag-v25 | `3d54492` | `5eec62a0c662` | current |

## Read the numbers with care

- **n = 3 per task.** Thirteen tasks × three runs is 39 runs. One run is 2.6 points, and a difference of one or two
  runs between configs is noise.
- **Runs cluster by task.** Almost every task passes 3/3 or 0/3, so the effective sample is closer to 13 tasks than to
  39 runs. Read the per-task table, not only the total, and use a task-level (clustered) bootstrap for intervals.
- **Results depend on the harness version.** The same planner scored 30/39 on v19 and 29/39 on v20 with identical
  tasks. Compare only within one version.
- **macOS only**, on one machine (Apple M4 Pro, macOS 27, zh-Hans locale, Peekaboo 4.3.0). The tasks are written in
  Chinese; other locales and OS versions are untested.
- **G03 (read a table from a web page) and G05 (ask before acting)** were unsolved by every config up to v21. The v25
  g14 router passed every task except G03; the v25 g18b router passes all thirteen, 3/3 each. With n = 3 that is not
  proof that G03 is solved for good: treat it as "no longer failing on this suite".
- **The suite is public.** Anyone can train on these tasks. Our own training tasks are generated separately and never
  include them.

## License

Apache-2.0, see `LICENSE` and `NOTICE`. The DeskMind name, 得心, the logo and Xiaofang are not covered by the code
licence. You may use them to refer to the project, but not in modified form or to imply endorsement.
