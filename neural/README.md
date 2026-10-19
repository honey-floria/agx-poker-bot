# 神经网络策略训练说明

本目录实现一条独立于现有启发式 `submission.js` 的神经网络路线。训练不会覆盖原模型；只有执行导出命令后，才会在根目录生成实验文件 `submission_nn.js`。

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
