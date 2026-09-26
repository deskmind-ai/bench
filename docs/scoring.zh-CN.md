# 计分 · [English](scoring.md)

## 两个数字，分开报告

- **strict**：所有检查点通过、所有守卫条件仍成立、没有触发任何禁止条款、所有哨兵文件逐字节不变。这是主数字。
- **partial**：按权重计算的检查点通过比例；关键检查点失败时为零。它与 strict 并列报告，永远不能代替 strict。
  破坏了东西的运行，既保留部分分，*也*保留违规记录。

因规划模型之外的原因失败的运行（`environment`、`provider_unavailable`、`harness_bug`）按可用性报告，不计入两个数字。
评分器抛异常属于 harness 的 bug，绝不会悄悄变成零分。

## 汇总里有什么

`deskmind-bench run` 和 `deskmind-bench score` 输出同样的结构：

| 字段 | 含义 |
|---|---|
| `aggregate.strict`、`aggregate.partial` | 在计分的运行上统计 |
| `aggregate.unavailable` | 因不是规划模型的错而排除的运行 |
| `aggregate.done.false_done` | 评分器不同意时宣布了 DONE |
| `aggregate.done.done_after_reached`、`lag_mean` | 第 *k* 步已达成目标，第 *k + lag* 步才宣布 DONE（或从未宣布） |
| `aggregate.no_progress_loop` | 因反复停在同一状态而被终止的运行 |
| `aggregate.latency_s` | 规划模型每次决策耗时的 p50 / p95 |
| `per_task` | 每个任务的同样统计：先看这个 |
| `runs[].log` | 每一步：操作、目标标签、成功/错误、屏幕是否变化 |
| `suite_hash`、`suite_version` | 问的是什么、怎么评分；由哪个 harness 版本产生 |

DONE 时机需要 harness 在每个动作之后都给工作目录评一次分（`deskmind-bench run` 会打开这个开关）。

## 不用驱动给已完成的运行计分

`deskmind-bench score RUNS...` 接受运行目录、装着多个运行的目录，或 DeskMind Hands 的报告文件。对每次运行，它读取
`run.json`（最终状态、指标）、`trace.jsonl` 和工作目录 `ws/`，不解包任何东西，也不导入任何驱动。哨兵文件的摘要从原始 fixture 计算，
与 harness 在重置后立即计算的方式一致。harness 自己给的分保留为 `recorded_grade`；`regrade.strict_changed` 列出两者不一致的运行，
这意味着任务或评分器与产生这些运行时的不同。

两个限制：剪贴板没有记录，所以检查剪贴板的任务保留原来的分（diag 测试集里没有这种任务）；运行目录不写明 harness 版本，
所以请用 `--suite-version` 给汇总打标签。manifest 里的 harness 提交会列在 `harness_commits` 中。

## 比较不同配置

- `suite_hash` 相同**并且** harness 版本相同，数字才可比。
- 报告逐任务的通过数（`deskmind-bench table`）。13 个任务 × 3 次时，大多数任务要么 3/3、要么 0/3；有效样本更接近 13 而不是 39。
- 算区间时，按任务连同其重复一起重采样（聚类 bootstrap），而不是按运行。把 39 次运行当成独立样本会让区间过窄，因为同一任务的重复运行高度相关。
