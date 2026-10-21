# NoRegrets 适配层

这里存放所有 NoRegrets 与 AGX 之间的适配、审计和数据转换代码。不要直接修改服务器上的上游 checkout。

主要入口：

- `check_environment.py`：许可、版本、补丁和二进制门禁。
- `audit_mapping.py`：AGX 与 NoRegrets 状态/动作映射审计。
- `run_smoke.py`：训练、恢复和蓝图查询冒烟。
- `run_formal_training.py`：三种子正式蓝图训练、滚动 checkpoint 和恢复。
- `run_ng4_evaluation.py`：可恢复的 NG-4A 高样本 duplicate 基线评测、动作审计与跨种子 crossplay。

NG-4A 只验证 NoRegrets 原生评测域。它不会替代与项目 TAG、Mixed 和当前正式 JavaScript 策略的同牌序评测，也不会自动允许学生查询。
