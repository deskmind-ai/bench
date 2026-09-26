# Harness versions · diag suite

Generated from `versions.json`.

The diag tasks, fixtures and graders are identical in all three versions (same suite hash). The version number is the harness's: how the desktop is presented to the planner and how actions are carried out. Numbers from different versions are not comparable.

| suite version | hands commit | suite hash | date | status | what changed in the harness |
|---|---|---|---|---|---|
| diag-v19 | `3aee984` | `5eec62a0c662` | 2026-09-25 | frozen | FOCUS_WINDOW is offered when there is one other window; scratch TextEdit windows say what they are; TextEdit saves are verified by the document's modified flag |
| diag-v20 | `7934cfa` | `5eec62a0c662` | 2026-09-26 | superseded | fixes from a real-desktop review task (the task app can be switched back to, a file-name guard, cmd+S on a scratch document goes through save-as, unreadable windows are refused, values listed with 分别 are split) and a hidden-state sweep (the new-folder value is shown, effects are listed in a parseable form, saves undone by later edits, a pending save-as tracked per window) |
| diag-v21 | `f1df118` | `5eec62a0c662` | 2026-09-26 | current | a colon after an ASCII word ("Status: final，") is not dictation, so "final，" is no longer offered as a value to type |

- **suite hash** covers the task files, the fixtures they use and the grader code (`deskmind-bench hash`). This checkout reproduces `5eec62a0c662`.
- **hands commit** is the harness commit in DeskMind Hands' development history that produced the numbers. The public repositories start from a single squashed commit, so these hashes identify versions but are not checkable in the public history; the harness version recorded in each summary (`suite_version`) is the key to compare on.
- **frozen**: no new numbers are produced on it; its reference results stay for comparison with each other.
