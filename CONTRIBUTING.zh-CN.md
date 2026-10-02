# 为得心 Bench 做贡献 · [English](CONTRIBUTING.md)

感谢参与！得心 Bench 是成绩的最终评分方，所以所有改动都用同一个标准衡量：改完之后，这个仓库给出的每个数字是否仍然准确表达它声称的含义？组织层面的通用规范（[deskmind-ai/.github](https://github.com/deskmind-ai/.github)）在这里同样适用，包括[行为准则](https://github.com/deskmind-ai/.github/blob/main/CODE_OF_CONDUCT.md)。

最有价值的两类贡献是新任务和成绩提交，两者都有对应的 issue 表单。

## 环境

```bash
git clone https://github.com/deskmind-ai/bench && cd bench
python -m venv .venv && . .venv/bin/activate
pip install -e .

python -m unittest discover -s tests -v   # 提 PR 前必须通过
deskmind-bench verify                     # 每个 diag 任务：oracle 能通过，什么都不做则失败
deskmind-bench hash                       # 未改动的仓库必须输出 5eec62a0c662
```

- 评分、自检和算哈希只需要 Python 3.11+ 和 PyYAML，不需要 Mac、驱动或模型，大多数 issue 在 Linux 上就能做。
- 真正执行任务需要一台装有 [DeskMind Hands](https://github.com/deskmind-ai/hands)（`pip install -e ".[run]"`）、Peekaboo 并授予权限的 Mac，见 README。

## 如何新增任务

第一次贡献？[30 分钟新增一个任务](docs/adding-a-task.zh-CN.md) 用一个真实的候选任务从头走一遍。

新任务放进单独的任务集 `tasks/proposals/`，不要放进 `tasks/diag/`。diag 的任务、它用到的 fixture 或评分器只要改一处，套件哈希就会变，已发布的所有数字都不再可比。候选任务由维护者统一升级为新的套件版本，并重新跑参考成绩。

先开一个 **New task proposal** issue。表单会问这个任务测什么、为什么走捷径过不了，大多数提案就是在这一步变好的。

**1. Fixture。** `fixtures/<name>/` 下的一个目录，每次运行前解包到一个全新的沙箱目录（`$WS`）。保持小巧、以纯文本为主。和所有 diag fixture 一样，放一个 `keep/reference.txt` 作为哨兵文件。

**2. 任务文件**，`tasks/proposals/Pnn-<app>-<what>.yaml`，格式定义在 `deskmind_bench/task.py`：

| 字段 | 含义 |
|---|---|
| `id`、`title`、`goal` | 唯一 id（即去掉 `.yaml` 的文件名）；简短标题；给 agent 的指令 |
| `app`、`surface`、`tags` | 首先观察的应用 bundle id（如 `com.apple.finder`，不要用显示名）；大类；自由标签 |
| `fixture` | `fixtures/` 下的目录名 |
| `stage`、`reset_apps` | agent 开始前执行的 shell 命令（打开任务前提需要的文档）；先关闭哪些应用的窗口 |
| `budget` | `max_actions`、`wall_clock_s`、`max_dialogue_turns` |
| `sentinels` | 结束时必须逐字节不变的文件，路径都以 `$WS/` 开头 |
| `grade.checkpoints` | `name`、`check`，可选 `weight`、`critical`（失败则部分分归零）、`process`（考察过程而非最终状态） |
| `grade.guards` | 结束时必须仍然成立；决定能否严格通过，但本身不给分 |
| `grade.forbid` | 不允许出现的副作用 |
| `user_script`、`inject` | 对 agent 提问的回复；从外部触发的事件（例如第 n 个动作时 `cancel`） |
| `oracle_effect` | 在 `$WS` 里执行、直接把工作区变成正确终态的 shell 命令 |

检查项是 `deskmind_bench/graders/primitives.py` 里的谓词（`file_text_equals`、`dir_manifest`、`file_count`、`run_field` 等），可以用 `all_of`、`any_of`、`not` 组合。避免 `clipboard_equals`：剪贴板不会被记录，这样的任务无法从磁盘重新评分。需要的检查项不存在时，先单独提一个 PR 新增谓词。

**3. Oracle 与空操作对照。** `oracle_effect` 证明任务可解、且评分器接受正确结果。空操作对照是未改动的 fixture，按「一开始就宣布完成」的运行来评分。`verify` 会同时跑这两项，两项都必须满足：

```bash
deskmind-bench verify --set proposals
```

- Oracle 达到**严格通过**：所有结果型 checkpoint 通过，没有 guard 被破坏，没有触发 forbid，哨兵文件未被改动。过程型 checkpoint 对 oracle 跳过，对每次真实运行都强制检查。
- 空操作对照得 **0 分**：不严格通过，且部分分恰好为 0。格式里有 `allow_vacuous`，但需要它的提案不会被接受。

任一项不满足，说明任务本身有问题，而不是任务难。同时 `deskmind-bench hash` 仍须输出 `5eec62a0c662`。

**沙箱规则。** 任务只能碰自己的工作区。`oracle_effect` 和 `stage` 只用相对 `$WS` 的路径，不用 `~`、绝对路径，也不联网。任务不能依赖用户主目录、账号或真实文档里的任何东西，也不能需要废纸篓、桌面或 iCloud。

**好任务的标准：** 只隔离一个 agent 容易出错的点；走捷径过不了（什么都不做、什么都做、写一个猜得到的常量、改错两份相似文件中的一份）；目标表达无歧义，除非考察的就是歧义；评分器检查结果，而不是某条特定路径。

## 如何提交成绩

先开一个 **Results submission** issue，再提一个 PR，在 `results/community/<suite_version>/` 下新增两个文件：

- `<label>.json`：下文描述的成绩条目；
- `<label>.summary.json`：`deskmind-bench run` 写出的汇总（如果你重新评分过，则是 `deskmind-bench score` 的输出）。

```bash
deskmind-bench run --set diag --repeats 3 --url http://127.0.0.1:8793 --label my-planner --out my-planner.summary.json
deskmind-bench table my-planner.summary.json
```

**规则：**

- **同一套件、同一 harness。** `suite_hash` 必须等于 `deskmind-bench hash` 的输出，也等于 `results/versions.json` 里你所用 `suite_version` 对应的哈希。请在标为 `current` 的版本上跑；`frozen` 版本不再接收新成绩。不同 harness 版本的成绩即使套件哈希相同也不可比，会分表列出。
- **准确写明 harness。** `hands_commit` 是你运行时 deskmind-ai/hands 的完整 commit，且没有本地改动。改过的 harness 就是另一个 harness：写明改了什么，条目会单独列出。
- **n ≥ 3。** 套件里每个任务至少跑三次，全部任务都要跑。如实报告结果，不要挑最好的一轮。
- **逐任务计数。** 每个任务的通过数、计分次数和环境错误数，加起来要等于总数。
- **环境错误单列。** 以 `environment`、`provider_unavailable` 或 `harness_bug` 结束的运行不计入严格通过率，记在 `env_errors` 里。这些运行可以重跑，规划器自己失败的运行不能重跑；重跑要在 `rounds` 和 `note` 里写明。
- **写明模型怎么部署的。** 权重、推理框架及版本、精度或量化、硬件、本地还是远程。托管 API 算远程，需要 `--allow-remote` 或 `--hosted`，写明用的哪个。
- 保留运行目录，我们可能会要来用 `deskmind-bench score` 重新评分。

**成绩条目**（`<label>.json`）在 `results/reference.json` 中 `configs` 单个元素的基础上，加上第三方需要说明的字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `schema` | string | `"deskmind-bench-results/1"` |
| `suite`、`suite_version`、`suite_hash` | string | `"diag"`、`"diag-v21"`、`"5eec62a0c662"` |
| `hands_commit` | string | 运行所用 deskmind-ai/hands 的完整 commit |
| `label`、`system` | string | 简称；一行描述系统及其版本 |
| `runs_on` | string | `"local, <芯片 / GPU>"` 或 `"cloud"` |
| `projection` | string | `"on"` 或 `"off"` |
| `repeats_per_task`、`rounds` | int | ≥ 3；运行分几次完成 |
| `runs`、`scored`、`env_errors`、`passed` | int | 总运行数；计分数；排除数；严格通过数。`runs = scored + env_errors` |
| `strict`、`partial` | float | `passed / scored`，保留 4 位小数；计分运行的平均部分分 |
| `false_done`、`no_progress_loops` | int | 取自汇总的 `aggregate` |
| `step_latency_s` | object 或 null | `{"p50": 秒, "p95": 秒}`，规划器每步决策耗时；无法合并时为 null |
| `per_task` | object | 套件中每个任务的 `{task_id: {"passed", "scored", "env_errors"}}` |
| `serving` | object | `{"weights", "stack", "precision", "hardware", "endpoint"}`：`weights` 是链接或 `"closed"`，`endpoint` 为 `"local"` 或 `"remote"` |
| `compute` | string | 运行总耗时，有费用则写上 |
| `submitted_by`、`date` | string | GitHub 用户名；运行日期（ISO 格式） |
| `note` | string | 可选：读者理解这些数字需要知道的任何信息 |

## 提交 PR

- **一个 PR 只做一件事**，简单说明改了什么、怎么验证的。
- **改评分要附证据。** 改评分器、评分程序或运行器时，附上对已有运行改动前后的 `deskmind-bench score` 输出，并写明哪些数字变了。如果套件哈希变了，PR 里要说明原因。
- **代码风格：** 跟周围代码保持一致，函数小，注释写「为什么」，评分部分不引入新依赖（只用 Python 和 PyYAML）。
- **检查清单：**
  - [ ] `python -m unittest discover -s tests` 和 `deskmind-bench verify --set <改过的每个任务集>` 通过；
  - [ ] `deskmind-bench hash` 仍输出 `5eec62a0c662`，或 PR 里说明了为什么变；
  - [ ] 任务和 fixture 不越出 `$WS`，不含真实个人数据；
  - [ ] 中英文档同步更新（`docs/*.md` 和 `docs/*.zh-CN.md`）。

## 反馈问题

- **任务或评分器的 bug**（正确的运行没通过，或错误的运行通过了）：附上任务 id、套件版本，以及该次运行的 `run.json` 和 `trace.jsonl`（去掉个人信息）。
- **安全问题：** 不要公开提 issue，见 [SECURITY.md](https://github.com/deskmind-ai/.github/blob/main/SECURITY.md)。

提交贡献即表示你同意贡献内容按本仓库的 Apache-2.0 许可发布。
