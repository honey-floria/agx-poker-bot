# NoRegrets 离线教师

本目录只保存可审计元数据、配置和小型清单。公开上游源码位于服务器独立目录 `/userhome/cs5/u3680889/third_party/noregrets`，以 detached HEAD 固定到 `757f7692738069522195d2b486eec60a8b010c0c`；完整上游仓库、蓝图和查询数据不得提交到本仓库。

## 当前门禁

- 上游 URL、commit、MIT 许可证、核心文件哈希、Cargo 锁文件和 Rust/Cargo 版本已固定。
- 上游没有 Git 子模块，也不发布预训练蓝图；README 明确预训练产物属于单独的商业许可。本项目禁止接入这些商业产物。
- 主办方已确认允许公开源码训练离线教师；部署限制仍保持不变。
- checkout 只应用 `tools/noregrets/patches/` 中三份可审计补丁：AGX 规则对齐、余数回归测试及 NG-3 blueprint 验证命令。
- 服务器计算节点已完成 `cargo test --release --locked`（137/137）及 `cargo build --release --locked`；当前 release 二进制 SHA-256 为 `b514f128ad5dfeeba14f0800b392fff9016d345fb23a2aa4322f99ee7cae5bd6`。上游 warning 不影响构建结果。

只检查本地清单完整性：

```bash
python3 tools/noregrets/check_environment.py status
```

在服务器 checkout 上核验 commit、文件哈希和工具链（只读，不启动训练）：

```bash
source "$HOME/.cargo/env"
python3 tools/noregrets/check_environment.py status \
  --source /userhome/cs5/u3680889/third_party/noregrets
```

训练入口必须使用 `require`。它会同时核验许可、补丁栈、工具链与 release 二进制哈希：

```bash
source "$HOME/.cargo/env"
python3 tools/noregrets/check_environment.py require \
  --source /userhome/cs5/u3680889/third_party/noregrets
```

固定构建命令为 `cargo build --release --locked`。不得省略 `--locked`，不得执行自动跟随 `main` 的 pull。

## CPU-only smoke

`tools/noregrets/noregrets_smoke.sbatch` 会在 Slurm 计算节点运行固定的 100 万次迭代 smoke，保存完整日志和 `/usr/bin/time -v` 资源统计，再从 checkpoint 恢复 10 万次迭代。随后它会跨进程重复查询同一批状态，检查概率归一化、合法动作、确定性和非退化性，并分别对 random/caller 基线执行小规模评测。smoke 产物明确禁止用于学生训练。

## 正式训练 v1

`blueprint-formal-v1.json` 保留上游 README 的六人 100BB、12 buckets、Pluribus menu、200 rollouts、24 runouts 和 30,000 k-means samples，但按照当前 64 GiB 内存与可用磁盘上限，将种子 7607、17607、27607 分别训练至 1 亿次迭代。`run_formal_training.py` 每 2,000 万次形成一个可恢复边界，每个种子只保留最近 3 个 zstd 压缩 checkpoint，并记录哈希、完整资源日志、确定性/概率合法性验证，以及相同种子和牌数的 random/caller 基线曲线。最终蓝图生成后删除未压缩的当前 checkpoint；中断后用同一条 `sbatch` 命令重提即可从最后一个保留并登记的 checkpoint 恢复。

上游 2 亿次标准方案已经实际启动，但单种子到 1 亿次时峰值内存约 51.9 GiB，继续扩展会超出可用资源，因此不把本次 1 亿次资源受限训练表述为标准方案复现。产物在通过 NG-4 教师评测前仍不得用于学生查询。

训练输出在通过 NG-4 前不得用于学生查询。提交命令：

```bash
sbatch /userhome/cs5/u3680889/noregrets-smoke-tools/repo/tools/noregrets/noregrets_formal.sbatch
```

## NG-4A 原生域评测

`ng4-eval-v1.json` 对三个最终蓝图分别执行 10,000 手确定性/合法性审计，以及对 random 和 caller 各 120,000 手的相同牌序六座轮换 duplicate evaluation；随后对三个种子的全部六个有向组合各执行 100,000 手 crossplay。`run_ng4_evaluation.py` 会重新核验蓝图 SHA-256、逐步骤登记进度，并支持同配置重提后续跑。

NG-4A 通过只表示三个蓝图在 NoRegrets 原生域显著优于弱基线且没有动作退化；仍须完成项目 TAG、Calling Station、Mixed 和当前正式 JavaScript 策略的同牌序评测，才能放行完整 NG-4。提交命令：

```bash
sbatch /userhome/cs5/u3680889/noregrets-smoke-tools/repo/tools/noregrets/noregrets_ng4_eval.sbatch
```
