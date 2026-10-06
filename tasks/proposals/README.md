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

## One goal, several jobs · 一个目标里几件事

`P03` to `P22` (`P03-finder-multi3-00.yaml` … `P22-finder-multi4-19.yaml`) are twenty generated variants of one idea:
a single goal that names three (P03–P12) or four (P13–P22) independent Finder jobs in one sandbox folder, drawn from
four kinds — make a folder and put a file in it, rename a file, move a file out of a subfolder to the top, add a suffix
to two files. Twelve are in Chinese, eight in English. Each job is one checkpoint (the new place holds the file **and**
the old place does not), so partial credit is the share of jobs done and deleting files earns nothing; two bystander
files per task are sentinels. The goal is one sentence on purpose: hands offers each line of a multi-line goal as text
to type ([deskmind#26](https://github.com/deskmind-ai/deskmind/issues/26)).

What they isolate: keeping several parts of a goal apart while the folder still shows what the earlier parts did. In
one run each on a real desktop (2026-10-06, released Peekaboo 4.7.0), the G18b router passed 0 of 20 while passing 40 of
42 one- and two-job tasks; a frontier model choosing every step through the same harness passed 4 of 19. The file and
folder names come from the same pools as hands' generated training tasks, so the vocabulary is not new to a model
trained on those; the composition is. They are proposals, not part of the published diagnostic suite, and do not change
its hash.

`P03` 到 `P22` 是同一个想法的二十个生成变体：一个目标里写了三件（P03–P12）或四件（P13–P22）互不相关的访达操作，
取自四类——新建文件夹并放入一个文件、给文件改名、把子文件夹里的文件移到顶层、给两个文件加后缀。十二个中文，八个英文。
每件事是一个检查项（新位置有、**并且**旧位置没有），所以部分得分等于做成了几件，只删文件不得分；每个任务有两个无关文件作为哨兵。
目标特意写成一句话：hands 会把多行目标的每一行当作可输入的文字（[deskmind#26](https://github.com/deskmind-ai/deskmind/issues/26)）。

它们隔离的是：文件夹里还留着前几件事的结果时，能不能把目标的各部分分开。真实桌面上各跑一次（2026-10-06，正式版 Peekaboo
4.7.0）：G18b 路由 20 个里通过 0 个，而同一个模型在单步和两步任务上是 42 个里通过 40 个；前沿模型通过同一套 harness 逐步选择，19 个里通过 4 个。
文件名和文件夹名取自 hands 生成训练任务所用的同一批词库，所以对在那些任务上训练过的模型，词汇不是新的，新的是组合方式。
它们是候选任务，不属于已发布的诊断集，不改变其哈希。

