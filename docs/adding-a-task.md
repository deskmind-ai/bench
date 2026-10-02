# Add a task in 30 minutes · [中文](adding-a-task.zh-CN.md)

A walk-through of one real proposal, [`tasks/proposals/P01-finder-copy.yaml`](../tasks/proposals/P01-finder-copy.yaml):
"copy report.txt into backup/, leave the original where it is". Everything here runs on any machine with Python
3.11+ and PyYAML. No Mac, no model. The reference is [CONTRIBUTING.md](../CONTRIBUTING.md#how-to-add-a-task).

## 0. Set up (5 min)

```bash
git clone https://github.com/deskmind-ai/bench && cd bench
python -m venv .venv && . .venv/bin/activate && pip install -e .
deskmind-bench verify --set proposals   # the existing proposals pass
deskmind-bench hash                     # 5eec62a0c662: proposals never change it
```

## 1. Pick one thing agents get wrong (5 min)

A good task isolates one mistake and cannot be passed by a shortcut. P01's mistake: asked to copy, an agent drags the
file (a move: the original is gone) or uses Finder's Duplicate (a stray `report copy.txt`). Write down the shortcuts
before writing anything else: doing nothing, doing it the wrong way, doing everything. Each one must fail.

Open a **New task proposal** issue with that paragraph. It is the part reviewers improve most.

## 2. The fixture (5 min)

A small directory under `fixtures/`, unpacked into a fresh sandbox folder (`$WS`) before every run:

```
fixtures/proposal_copy/
  report.txt            # the file to copy
  notes.txt             # an unrelated file that must not change
  backup/README.txt     # the destination exists (git keeps no empty folders)
  keep/reference.txt    # the sentinel every fixture carries
```

Plain text only, no personal data, nothing outside `$WS`.

## 3. The task file (10 min)

```yaml
id: P01-finder-copy
app: com.apple.finder                 # a bundle id, never a display name
goal: |
  把工作目录里的 report.txt 复制一份到 backup 文件夹里。原来的 report.txt 要留在原处，不要改动其他文件。
fixture: proposal_copy
budget: {max_actions: 15, wall_clock_s: 600}
sentinels: ["$WS/keep/reference.txt", "$WS/notes.txt", "$WS/backup/README.txt"]
grade:
  checkpoints:                        # what the task is for; earns partial credit
    - name: copied
      critical: true
      check: {file_text_equals: {path: "$WS/backup/report.txt", value: "Q3 report\nrevenue: 1240\n"}}
  guards:                             # must still hold, earns nothing (an untouched folder satisfies it)
    - {file_text_equals: {path: "$WS/report.txt", value: "Q3 report\nrevenue: 1240\n"}}
  forbid:                             # side effects of the wrong route
    - {file_exists: {path: "$WS/report copy.txt"}}
    - {file_exists: {path: "$WS/report 副本.txt"}}
oracle_effect:                        # shell, inside $WS: the correct end state, directly
  - cp report.txt backup/report.txt
```

Why "the original is still there" is a **guard** and not a checkpoint: an untouched folder satisfies it, so as a
checkpoint it would give doing nothing partial credit, and `verify` rejects that. The checks you can use are listed in
[`graders/primitives.py`](../deskmind_bench/graders/primitives.py).

## 4. Verify (2 min)

```bash
deskmind-bench verify --set proposals
#   [OK ] P01-finder-copy
deskmind-bench hash                   # still 5eec62a0c662
```

`verify` runs the oracle (it must reach strict success) and the null control (doing nothing must score exactly 0).

## 5. Try the wrong endings (3 min)

The shortcuts from step 1 must fail too. Grade a hand-made ending:

```python
import subprocess, tempfile
from pathlib import Path
from deskmind_bench.task import load_task
from deskmind_bench.verify import GradeContext, _unpack, grade, pristine_sentinels

task, fx = load_task(Path("tasks/proposals/P01-finder-copy.yaml")), Path("fixtures")
for name, cmd in [("copy", "cp report.txt backup/"), ("move", "mv report.txt backup/"),
                  ("duplicate", "cp report.txt 'report copy.txt'; cp report.txt backup/")]:
    with tempfile.TemporaryDirectory() as d:
        ws = _unpack(task, fx, Path(d))
        subprocess.run(cmd, shell=True, cwd=ws, check=True)
        g = grade(task, GradeContext(workspace=ws, vars=task.vars, run={"state": "completed", "metrics": {}}),
                  sentinel_digests=pristine_sentinels(task, fx))
        print(name, "strict" if g.strict else "fails", g.violations)
# copy strict [] / move fails [...] / duplicate fails [...]
```

## 6. Open the PR

The task file and the fixture, nothing in `tasks/diag/`. The PR template asks for the `verify` output and your wrong
endings. Running the task on a Mac with an agent is welcome but not required: maintainers run accepted proposals
before they join a new suite version.
