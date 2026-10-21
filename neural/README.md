# 神经网络策略训练说明

本目录实现一条独立于现有启发式 `submission.js` 的神经网络路线。训练不会覆盖原模型；只有执行导出命令后，才会在根目录生成实验文件 `submission_nn.js`。

## 公开回放行为克隆 v2

`train_behavior_clone_v2.py` 是当前公开回放主训练入口。它使用 232 维、整桌旋转不变的公开状态特征，共享 MLP 主干后分为两个任务：先预测 `fold/check/call/raise/all-in` 动作族，只在普通加注样本上预测六个下注尺度。动作族在训练和评估时都应用合法动作硬掩码；类别权重采用上限为 3 的平方根反频率，避免 v1 严重过度预测罕见大尺度加注。

服务器 GPU 环境中先运行两轮冒烟：

```bash
.venv/bin/python neural/train_behavior_clone_v2.py \
  --device cuda \
  --epochs 2 \
  --patience 2 \
  --loader-workers 0 \
  --output-dir neural/artifacts/behavior-v2-smoke
```

通过后运行正式训练：

```bash
.venv/bin/python neural/train_behavior_clone_v2.py \
  --device cuda \
  --epochs 60 \
  --patience 8 \
  --batch-size 2048 \
  --loader-workers 0 \
  --output-dir neural/artifacts/behavior-v2
```

报告同时包含验证集和一次性测试集的动作族准确率、宏平均 F1、加注尺度准确率、组合十动作准确率及完整混淆矩阵。实验配置固定在 `poker-distill/experiments/behavior_v2.json`。

## Top-20 教师数据

第一批 100 场回放是总体玩家样本，不能视为强手教师。Top-20 路线先固定排行榜快照，从最近比赛中均衡选择含第 1–20 名的 300 场完整回放；构建数据集时仅把这些强手的动作当作监督标签，但保留同桌所有玩家的公开状态作为输入上下文。教师姓名只保存在 Git 忽略的原始下载清单中，训练 JSONL 只含匿名玩家和教师名次档位。

服务器上下载并构建数据：

```bash
set -a
source .env.local
set +a
python3 tools/download_agx_top_teacher_replays.py \
  --output-dir poker-distill/data/raw-replays/top20 \
  --top-k 20 --matches 300 --scan-jobs 2000 --workers 3
python3 tools/build_top_teacher_dataset.py \
  --raw-dir poker-distill/data/raw-replays/top20 \
  --output-dir poker-distill/data/parsed-decisions/top20 \
  --top-k 20 --required 300
```

训练器会从 JSONL 自动读取并校验 `data_version`。先训练不加类别权重版本；随后用相同划分训练平方根反频率版本作对照：

```bash
.venv/bin/python neural/train_behavior_clone_v2.py \
  --data-dir poker-distill/data/parsed-decisions/top20 \
  --device cuda --epochs 60 --patience 8 --batch-size 2048 \
  --loader-workers 0 --class-weighting none \
  --output-dir neural/artifacts/behavior-v3-top20-unweighted

.venv/bin/python neural/train_behavior_clone_v2.py \
  --data-dir poker-distill/data/parsed-decisions/top20 \
  --device cuda --epochs 60 --patience 8 --batch-size 2048 \
  --loader-workers 0 --class-weighting sqrt --max-class-weight 3 \
  --output-dir neural/artifacts/behavior-v3-top20-sqrt
```

实验配置固定在 `poker-distill/experiments/behavior_v3_top20.json`。离线准确率只用于选检查点，是否晋级仍以固定牌序对战收益、非法动作、超时和运行预算为准。

## 困难状态安全重标注（round 1）

`tools/label_policy_states.js` 为每个困难状态创建隔离的 JavaScript 上下文，并使用当前正式 `submission.js` 生成冷启动安全标签；它不会伪装成求解器标签，也不会使用跨手对手统计。`tools/build_dagger_dataset.py` 只替换 Top-20 训练 split 中匹配的 10,000 条标签，validation/test 保持原始 Top-20 标签。完整三种子 GPU 作业入口为：

```bash
sbatch tools/run_dagger1_heuristic.sbatch
```

输出数据位于 `poker-distill/data/dagger/round_1/dataset-heuristic/`，模型位于 `neural/artifacts/behavior-dagger1-heuristic-seed-*/`。这一步属于安全困难状态重标注，不勾选“求解器重新标注”；候选仍须通过固定牌序 paired evaluation 才能晋级。

三种子训练完成后，使用 `tools/run_dagger1_screening.sbatch` 启动可恢复的 round-1 快速筛选。它对 9 个候选（每个种子的独立策略、0.95 与 0.99 翻后门控策略）分别运行 200 个完整 match，对手为当前正式策略和 TAG；另以相同牌序运行当前正式策略对 TAG 作为配对参考。报告采用整局 bootstrap 95% 区间，只有零非法动作、零超时且对当前正式策略的区间下界为正的候选，才允许进入更高样本量的正式评测。

## 模型与算法

模型是一个适合嵌入 QuickJS 的小型多层感知机：

```text
32个局面特征 → 64维ReLU → 32维ReLU → 4个动作类别
```

四个类别分别代表弃牌/免费过牌、跟注/过牌、小额主动下注和大额主动下注。输入包含街道、位置、手牌点数、对子/同花/间隔、成牌类别、听花与牌面结构、底池、跟注额、筹码、底池赔率、SPR、对手数量和行动历史等信息。

监督标签由一个保守的离线教师生成：它为随机局面做范围约束的蒙特卡洛胜率估计，再根据底池赔率、SPR、牌面结构和近似跟注EV分配动作类别。网络使用带类别权重的交叉熵损失和 AdamW 优化，验证损失长期不改善时提前停止。

这属于“策略蒸馏/行为克隆”，不是完整的 CFR 或强化学习。第一版的目标是先验证数据、GPU训练、QuickJS导出和同牌序对战整条链路，再根据实战结果迭代标签与训练目标。

## 文件说明

- `data.py`：生成随机局面、计算32维特征、蒙特卡洛估值并产生教师标签。
- `train.py`：使用 PyTorch 在 CUDA 或 CPU 上训练网络，保存检查点和报告。
- `submission_nn.template.js`：零依赖 QuickJS 推理与动作映射模板。
- `export_submission.py`：把 JSON 权重嵌入模板，生成根目录 `submission_nn.js`。
- `artifacts/`：训练数据、模型和报告目录；大文件默认不提交 Git。

## 服务器训练

这次修改只保存在本地。先在本地终端把训练目录和更新后的校验器传到服务器：

```bash
cd /Users/ys/Documents/7607/agx-poker-bot
scp -P 22222 -o HostKeyAlias=gpu2gate1.cs.hku.hk -r \
  neural \
  u3680889@127.0.0.1:/userhome/cs5/u3680889/agx-poker-bot/
scp -P 22222 -o HostKeyAlias=gpu2gate1.cs.hku.hk \
  tools/validate.py \
  u3680889@127.0.0.1:/userhome/cs5/u3680889/agx-poker-bot/tools/validate.py
```

如果之后已经把本地修改提交并推送到 GitHub，也可以在服务器用 `git pull --ff-only origin main` 代替上面的 `scp`。传输完成后登录服务器并申请交互式 GPU：

```bash
ssh -p 22222 -o HostKeyAlias=gpu2gate1.cs.hku.hk u3680889@127.0.0.1
cd /userhome/cs5/u3680889/agx-poker-bot
gpu-interactive
```

`gpu-interactive` 会进入新的 GPU shell。进入后重新切到项目目录，并用 `uv` 建立环境：

```bash
cd /userhome/cs5/u3680889/agx-poker-bot
test -x .venv/bin/python || uv venv --python 3.10 .venv
uv pip install --python .venv/bin/python torch numpy
.venv/bin/python -c "import torch; print(torch.__version__); print(torch.cuda.get_device_name(0)); print(torch.cuda.is_available())"
```

建议先做一次小规模流水线冒烟测试：

```bash
.venv/bin/python neural/train.py \
  --pipeline-smoke \
  --samples 10000 \
  --mc-samples 12 \
  --epochs 5 \
  --batch-size 2048 \
  --workers 24 \
  --device cuda
.venv/bin/python neural/export_submission.py
.venv/bin/python tools/validate.py submission_nn.js
```

只有 `poker-distill/reports/environment_validation.json` 已记录至少100局公开回放逐动作验证并将门禁标记为通过后，才能运行正式训练：

```bash
.venv/bin/python neural/train.py \
  --samples 200000 \
  --mc-samples 48 \
  --epochs 60 \
  --batch-size 4096 \
  --workers 24 \
  --loader-workers 2 \
  --patience 10 \
  --device cuda
.venv/bin/python neural/export_submission.py
.venv/bin/python tools/validate.py submission_nn.js
```

数据生成主要使用 CPU 多进程，网络训练才使用 GPU，因此开始训练前出现一段 GPU 利用率较低的时间属于正常情况。若只想用同一批数据调整训练轮数或学习率，可增加 `--reuse-data`，避免重新生成 `dataset.jsonl`。

## 训练产物

训练完成后会生成：

```text
neural/artifacts/dataset.jsonl
neural/artifacts/model.pt
neural/artifacts/model.json
neural/artifacts/training_report.json
submission_nn.js
```

请把控制台最后几十行和 `neural/artifacts/training_report.json` 发回来。随后应在相同牌序上比较 `submission_nn.js`、现有 `submission.js` 和旧基线，不能仅凭训练准确率判断扑克收益。

## 本地对战命令

服务器若安装了 Node.js，可以在导出后直接运行：

```bash
node simulator/simulate_submission.js \
  --candidate submission_nn.js \
  --opponent submission.js \
  --matches 30 \
  --seed 7607
```

神经网络只有在多个随机种子下没有非法动作、没有超时，并且平均净额或第一名份额稳定优于现有版本时，才考虑替换正式提交文件。
