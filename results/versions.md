# Harness versions · diag suite

Generated from `versions.json`.

The diag tasks, fixtures and graders are identical in all versions (same suite hash). The version number is the harness's: how the desktop is presented to the planner and how actions are carried out. Numbers from different versions are not comparable.

| suite version | hands commit | suite hash | date | status | what changed in the harness |
|---|---|---|---|---|---|
| diag-v19 | `3aee984` | `5eec62a0c662` | 2026-09-25 | frozen | FOCUS_WINDOW is offered when there is one other window; scratch TextEdit windows say what they are; TextEdit saves are verified by the document's modified flag |
| diag-v20 | `7934cfa` | `5eec62a0c662` | 2026-09-26 | superseded | fixes from a real-desktop review task (the task app can be switched back to, a file-name guard, cmd+S on a scratch document goes through save-as, unreadable windows are refused, values listed with 分别 are split) and a hidden-state sweep (the new-folder value is shown, effects are listed in a parseable form, saves undone by later edits, a pending save-as tracked per window) |
| diag-v21 | `f1df118` | `5eec62a0c662` | 2026-09-26 | frozen | a colon after an ASCII word ("Status: final，") is not dictation, so "final，" is no longer offered as a value to type |
| diag-v22 | `1c3f47d` | `5eec62a0c662` | 2026-09-27 | frozen | timing-only harness changes: staging polls instead of sleeping for fixed times, no button-by-button alert fallback when there is no dialog, the permission probe can be skipped by the host |
| diag-v23 | `713961b` | `5eec62a0c662` | 2026-09-27 | frozen | value options include whole record lines (in the shape of the goal's template, or separated cells with an identifier), so a record can be copied whole |
| diag-v24 | `4d12033` | `5eec62a0c662` | 2026-09-27 | frozen | staging no longer launches TextEdit bare to close its documents (a bare launch left a hidden Open panel), and TextEdit is launched without state restoration |
| diag-v25 | `3d54492` | `5eec62a0c662` | 2026-09-28 | frozen | a write refused as already done refuses only that text (dropped from the value options), no longer every way to write the field |
| diag-v26 | `11368c6` | `5eec62a0c662` | 2026-10-05 | current | the first version on the public DeskMind Hands (the harness of the DeskMind app 0.4.0): every change in v25, plus the check before DONE, approvals asked by the harness before sending, deleting, paying, publishing and sharing, choice questions kept within the protocol's 1..255 options, and at most 40 dropdown options in the state and the SELECT head (none of the diag tasks has that many) |

- **suite hash** covers the task files, the fixtures they use and the grader code (`deskmind-bench hash`). This checkout reproduces `5eec62a0c662`.
- **hands commit** is the harness commit in DeskMind Hands' development history that produced the numbers. That history was rebuilt into a single public commit on 2026-10-02 (`20f6779`), so none of these commits can be checked out. They name the version; the "what changed" column says what it did. The harness version recorded in each summary (`suite_version`) is the key to compare on.
- **Rerunning an old version** exactly is not possible from the public repositories. The public DeskMind Hands is newer than every version here: it contains each change listed, and later ones. The reference numbers stay as a record. New reference runs are made on the public DeskMind Hands and published under a new harness version, with its commit.
- **frozen**: no new numbers are produced on it; its reference results stay for comparison with each other.
