# Task proposals · 候选任务

New tasks start here, never in `tasks/diag/`: a change there moves the suite hash and every published number stops
being comparable. Each proposal must pass `deskmind-bench verify --set proposals`. See
[How to add a task](../../CONTRIBUTING.md#how-to-add-a-task).

新任务先放在这里，不要放进 `tasks/diag/`。每个候选任务都必须通过 `deskmind-bench verify --set proposals`，见
[如何新增任务](../../CONTRIBUTING.zh-CN.md#如何新增任务)。

## Replace every occurrence · 全部替换

[`P02-textedit-replace-all.yaml`](P02-textedit-replace-all.yaml) asks an agent to replace all three occurrences of
`Orion` with `Nova` in `memo.txt` and save without changing other text. A critical whole-file check rejects replacing
only one or two occurrences; `keep/reference.txt` must remain byte-identical. This is a proposal, not part of the
published diagnostic suite, and does not change its hash.

[`P02-textedit-replace-all.yaml`](P02-textedit-replace-all.yaml) 要求代理把 `memo.txt` 中三处 `Orion` 全部替换为 `Nova`，
保存文件，并保持其他文字不变。关键检查比对整个文件，只替换一处或两处不能通过；
`keep/reference.txt` 必须保持字节一致。本任务是候选任务，不属于已发布的诊断集，不改变其哈希。
