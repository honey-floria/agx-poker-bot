# 扑克蒸馏工作区

本目录保存数据处理、教师、学生模型、运行时、评测和实验记录。大型原始数据与提交产物默认被 Git 忽略；目录中的 `.gitkeep` 只用于保留结构。

## 实验生命周期

从模板复制并填写配置，然后创建实验：

```bash
cp poker-distill/experiments/config.template.out /tmp/E01_config.out
python3 tools/experiment_registry.py create \
  --id E01_baseline \
  --config /tmp/E01_config.out \
  --training-data synthetic-v1 \
  --data-version solver-mix-v1 \
  --seed 7607 \
  --teacher-version heuristic-v1 \
  --model-structure 32x64x32x4 \
  --loss-weights ce=1.0 \
  --quantization float32
```

训练结束后登记模型哈希和离线结果：

```bash
python3 tools/experiment_registry.py complete \
  --id E01_baseline \
  --model neural/artifacts/model.out \
  --offline-results '{"validation_accuracy":0.71,"mbb_per_hand":12.3}'
```

上线后补充版本号，并检查整个登记表：

```bash
python3 tools/experiment_registry.py set-online --id E01_baseline --online-version agx-v17
python3 tools/experiment_registry.py check
python3 tools/experiment_registry.py list
```

实验编号必须匹配 `E<至少两位数字>_<名称>`，且不可重复。每个实验会在 `experiments/<编号>/` 中保存配置快照和 `manifest.json`；汇总字段同时写入 `experiments/experiments.csv`。
