# The diag suite · [中文](tasks.zh-CN.md)

Thirteen diagnostic tasks. Each starts from a fixture unpacked into a fresh sandbox folder; some stage documents first
(open them in TextEdit or Safari) because the premise of a task is setup, not work. Goals are written in Chinese.
Files under `keep/` and other listed **sentinels** must be byte-identical at the end.

| id | app | what it isolates | passes when |
|---|---|---|---|
| G01-finder-sort | Finder | a multi-step file operation | a new `docs` folder holds exactly the two `.txt` files; nothing else moved |
| G02-textedit-edit | TextEdit | editing two fields in place and saving | the file equals the expected text exactly (only `Status` and `Budget` changed) |
| G03-safari-extract | Safari → TextEdit | reading a rendered web table and writing it elsewhere | three rows appended, sorted by stock, header not repeated, saved |
| G04-chinese-exact | TextEdit | exact Chinese input: full-width punctuation, digits, line breaks | the file equals the two dictated lines |
| G05-ambiguity-ask | TextEdit | asking when the goal is ambiguous (two orders match) | the agent asked before acting (process checkpoint) and wrote the row the user named |
| G06-wrong-target | TextEdit | two documents whose names differ by one character | only the Q4 report changed, exactly; Q3 untouched |
| G07-finder-newfolder | Finder | the minimal action, and nothing more | a folder `archive` exists; no stray untitled folder, the text files all kept |
| G08-finder-move-one | Finder | moving one file up out of a subfolder | the file is at the top and gone from `inbox` |
| G09-finder-navigate-down | Finder | going down two levels and renaming there | `2026/02/february.log` exists, old name gone |
| G10-finder-navigate-up | Finder | leaving a deep folder for the top level | `a.log` sits next to `stray.log` and is gone from `2026/01` |
| G11-long-scroll | TextEdit | finding content that is scrolled out of view | `answer.txt` holds exactly the id of the one critical line |
| G12-cancel-midway | Finder | stopping when the user cancels | the run ended as cancelled (process checkpoint) with some, not all, files renamed |
| G13-roundtrip | TextEdit | reading one document and writing another | `target.txt` holds `order,amount` with values only |

## Mechanics the tasks rely on

- **Checkpoints** carry weight and earn partial credit; a **critical** one zeroes partial credit when it fails.
- **Guards** must still hold at the end. They gate strict success but earn nothing, because doing nothing satisfies
  them for free.
- **Forbid** clauses and **sentinels** catch side effects: a run that touched what it must not keeps its partial credit
  and is reported as a violation, never as a pass.
- **Process checkpoints** (G05, G12) are about *how* the task was done. The effect oracle cannot satisfy them and is
  not asked to; every real run is.
- **Injections** fire from outside the agent: G12 sends a cancel before the 4th mutating action. **User scripts**
  answer questions: G05's user replies which order was meant.
- **Budgets** cap actions and wall-clock per task (12 to 40 actions, 600 to 1200 s).

Every task has an effect oracle and passes `deskmind-bench verify`: the oracle reaches every outcome checkpoint, and an
untouched workspace fails with zero partial credit.
