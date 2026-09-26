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
  <b>DeskMind Bench</b> · 沙箱化的 macOS 桌面任务、评分器和参考结果。<br>
  <a href="README.md">English</a> · <a href="docs/tasks.zh-CN.md">任务</a> · <a href="docs/scoring.zh-CN.md">计分</a> ·
  <a href="results/reference.md">结果</a> · <a href="results/versions.md">版本</a>
</p>

---

**DeskMind · 得心** —— *得心，应手。* 一组开源项目，让智能体在你自己的电脑上**看**屏幕、**想**下一步、**做**出操作，全部在本地完成。

这个仓库是 **Bench（基准）**：我们桌面数字所用的任务集、给它评分的评分器，以及作为依据的计分程序。DeskMind 的每个结果都会注明这里的
套件哈希和 harness 版本。

| | 仓库 | 作用 |
|---|---|---|
| 👁 | [deskmind-ai/eyes](https://github.com/deskmind-ai/eyes) | 在截图上找到目标 |
| 🧠 | [deskmind-ai/brain](https://github.com/deskmind-ai/brain) | 决定下一步，并给出校准过的置信度 |
| ✋ | [deskmind-ai/hands](https://github.com/deskmind-ai/hands) | 操作真实的 macOS 桌面 |
| 📐 | **deskmind-ai/bench** | 沙箱桌面任务与评分器，用来复现我们的数字 |

## diag 测试集考什么

13 个任务，在真实的访达、文本编辑和 Safari 上进行，每个都在从 fixture 解包出来的沙箱文件夹里。每个任务专门考桌面智能体容易出错的一件事
（见 [docs/tasks.zh-CN.md](docs/tasks.zh-CN.md)）：

- **访达操作：** 新建文件夹、移动文件、向下进入两层再返回上层、把文件归类到新文件夹、依次重命名多个文件。
- **精确编辑文字：** 改两个字段并保存；逐字输入带全角标点的中文；在需要滚动的 60 行日志里找到一行。
- **跨应用：** 从 Safari 读一张表，排序后追加进 CSV；把一个文档里的值抄到另一个文档。
- **行为得体：** 目标有歧义时先问而不是猜；两份几乎一样的文档只改指定的那份；中途被取消就停下。

一次运行只有在所有检查点都通过、没有破坏任何守卫条件、没有禁止的副作用、哨兵文件原封不动时，才算通过（**strict**）。
部分得分单独报告，永远不能代替 strict。

## 运行与计分

计分只需要 Python 和 PyYAML：不需要 Mac、驱动或模型。

```bash
git clone https://github.com/deskmind-ai/bench && cd bench
pip install -e .

deskmind-bench verify                  # 每个任务：效果 oracle 通过，什么都不做则失败
deskmind-bench hash                    # 5eec62a0c662，即参考结果的套件哈希
deskmind-bench versions                # harness 版本及其提交
deskmind-bench score path/to/runs/ --suite-version diag-v21 --out mine.json   # 从磁盘重新给已完成的运行评分
deskmind-bench table mine.json         # 每个任务的通过数，输出 markdown 表格
```

`score` 读取 [DeskMind Hands](https://github.com/deskmind-ai/hands) 写下的每次运行的工作目录、运行记录和轨迹，用本仓库的评分器重新评分，
报告 strict 与部分通过率、错误的 DONE、DONE 时机和每步延迟。它从不导入驱动。

执行运行需要一台装了 DeskMind Hands、Peekaboo 并授予权限的 Mac，以及一个提供 `/v1/systemone` 的规划模型：

```bash
pip install -e ".[run]"                # 会装上 deskmind-hands
deskmind-bench run --set diag --repeats 3 --url http://127.0.0.1:8793 --label my-planner --out my-planner.json
```

除非传 `--allow-remote`，运行器拒绝非本地地址；除非要求跑托管参考（`--hosted`），它会把托管 API 的密钥从环境变量里移除。

## 参考结果

真实 macOS 桌面，13 个任务 × 3 次，投影层开启，strict 通过率。完整的逐任务表格见
[results/reference.md](results/reference.md)（以及 `reference.json`）。

| harness | 配置 | strict 通过 | 错误的 DONE | 每步 p50 |
|---|---|---|---|---|
| v21 | DeskMind Brain 路由（0.8B → 4B），v7b | **32/39（82%）** | 2 | 3.3 秒 |
| v20 | Jev（TypeSafe AI，云端参考） | 33/39（85%） | 0 | 0.4 秒 |
| v20 | DeskMind Brain 路由，v7 | 29/39（74%） | 3 | 3.2 秒 |
| v19 | DeskMind Brain 路由，v7 | 30/39（77%） | 2 | 3.6 秒 |
| v19 | DeskMind Brain 4B，g11b | 27/39（69%） | 3 | 3.4 秒 |
| v19 | DeskMind Brain 4B，g10b | 24/39（62%） | 7 | – |
| v19 | Jev（TypeSafe AI，云端参考） | 31/37（84%），2 次环境错误 | 2 | 1.0 秒 |

## 版本

三个版本的任务、fixture 和评分器完全相同（套件哈希 `5eec62a0c662`）。变的是 harness：桌面如何呈现给规划模型、动作如何执行。
每个版本改了什么，见 [results/versions.md](results/versions.md)（以及 `versions.json`）。

| 套件版本 | hands 提交 | 套件哈希 | 状态 |
|---|---|---|---|
| diag-v19 | `3aee984` | `5eec62a0c662` | 冻结 |
| diag-v20 | `7934cfa` | `5eec62a0c662` | 已被取代 |
| diag-v21 | `f1df118` | `5eec62a0c662` | 当前 |

## 读数字时请小心

- **每个任务 n = 3。** 13 个任务 × 3 次是 39 次运行。一次运行就是 2.6 个百分点，配置之间差一两次运行属于噪声。
- **运行按任务聚集。** 几乎每个任务要么 3/3、要么 0/3，所以有效样本更接近 13 个任务而不是 39 次运行。请看逐任务表，而不只是总数；
  算区间时请按任务做聚类 bootstrap。
- **结果取决于 harness 版本。** 同一个规划模型在任务完全相同的情况下，v19 得 30/39，v20 得 29/39。只在同一版本内比较。
- **只支持 macOS**，并且只在一台机器上测过（Apple M4 Pro、macOS 27、简体中文系统语言、Peekaboo 4.3.0）。任务用中文写成；
  其他语言环境和系统版本没有测过。
- **有两个任务所有配置都没解出来：** G03（从网页读表格）和 G05（行动前先提问）。表中没有任何配置通过超过 13 个任务中的 11 个。
- **测试集是公开的。** 任何人都可以在这些任务上训练。我们自己的训练任务是另外生成的，从不包含它们。

## 许可

Apache-2.0，见 `LICENSE` 和 `NOTICE`。DeskMind 名称、得心、标志和小方不在代码许可范围内：可以用来指代本项目，
但不能修改后使用，也不能用来暗示背书。
