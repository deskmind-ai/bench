# 30 分钟新增一个任务 · [English](adding-a-task.md)

以一个真实的候选任务 [`tasks/proposals/P01-finder-copy.yaml`](../tasks/proposals/P01-finder-copy.yaml) 为例，走一遍全过程：
“把 report.txt 复制到 backup/ 里，原文件留在原处”。下面每一步都只需要 Python 3.11+ 和 PyYAML，不需要 Mac，也不需要模型。完整规则见 [CONTRIBUTING.zh-CN.md](../CONTRIBUTING.zh-CN.md#如何新增任务)。

## 0. 准备（5 分钟）

```bash
git clone https://github.com/deskmind-ai/bench && cd bench
python -m venv .venv && . .venv/bin/activate && pip install -e .
deskmind-bench verify --set proposals   # 已有的候选任务都能通过
deskmind-bench hash                     # 5eec62a0c662：候选任务不会改变它
```

## 1. 选一个智能体常犯的错（5 分钟）

好的任务只考一个错误，而且走捷径过不了。P01 考的是：让它“复制”，它却把文件拖过去（变成移动，原文件没了），或者用访达的“复制”生成一个多余的 `report copy.txt`。动笔之前先把捷径列出来：什么都不做、用错方法做、全都做一遍。每一种都必须判失败。

先开一个 **New task proposal** issue，写清这一段。评审意见大多集中在这里。

## 2. 准备 fixture（5 分钟）

`fixtures/` 下的一个小目录，每次运行前会解压到一个全新的沙盒文件夹（`$WS`）：

```
fixtures/proposal_copy/
  report.txt            # 要复制的文件
  notes.txt             # 无关文件，不能被改动
  backup/README.txt     # 目标文件夹已存在（git 不保留空文件夹）
  keep/reference.txt    # 每个 fixture 都带的哨兵文件
```

只放纯文本，不放个人数据，不引用 `$WS` 之外的任何东西。

## 3. 写任务文件（10 分钟）

内容见 [英文版第 3 步](adding-a-task.md#3-the-task-file-10-min) 的 YAML，和仓库里的 P01 完全一致。

“原文件还在”为什么写成 **guard** 而不是 checkpoint：什么都不做时它也成立。写成 checkpoint 的话，什么都不做也能拿到部分分，`verify` 会拒绝。可用的检查见 [`graders/primitives.py`](../deskmind_bench/graders/primitives.py)。

## 4. 自检（2 分钟）

```bash
deskmind-bench verify --set proposals
#   [OK ] P01-finder-copy
deskmind-bench hash                   # 仍然是 5eec62a0c662
```

`verify` 会跑 oracle（必须严格通过），也会跑空白对照（什么都不做必须正好 0 分）。

## 5. 试几个错误结局（3 分钟）

第 1 步列出的捷径也必须判失败。用 [英文版第 5 步](adding-a-task.md#5-try-the-wrong-endings-3-min) 的脚本给手工做出的结局打分：复制严格通过，移动和多出副本都判失败。

## 6. 提交 PR

只提交任务文件和 fixture，不要改 `tasks/diag/`。PR 模板会要你贴 `verify` 的输出和你试过的错误结局。欢迎在 Mac 上用智能体实际跑一遍，但不是必须：候选任务被接受后，维护者会在并入新版本套件前统一跑。
