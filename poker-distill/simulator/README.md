# 精确比赛引擎

`engine.py` 是冻结到 `rsi-poker-4.1` 的六人无限注德州扑克状态机，覆盖本街累计 `to`、最小/最大加注、短全下的重新开放规则、无人跟注筹码退回、主池/边池、平分底池余数以及六阶段复式赛程。

运行十万手随机合法动作压力测试：

```bash
python3 poker-distill/simulator/stress.py --hands 100000 --seed 7607 \
  --report poker-distill/reports/engine_stress_100k.out
```

该引擎是离线数据与一致性验证的规则基准。正式 `submission.js` 的 Node.js 对战模拟器仍负责性能和策略对战，两者由测试中的固定边界案例共同约束。
