# AGX 六人无限注德州扑克 AI

这是一个面向 AGX 六人无限注德州扑克比赛的零依赖项目，包含正式提交 AI、合法性测试、配对牌局模拟器，以及一个可由真人参与的浏览器牌桌。

## 文档

- [项目结构说明](doc/PROJECT_STRUCTURE.md)：用树形结构说明每个目录和文件的用途。
- [完成情况与待办事项](doc/TODO.md)：记录已经完成的工作、当前限制和后续开发顺序。
- [蒸馏与冲榜计划](doc/蒸馏TODO.md)：记录冻结的比赛约束和蒸馏路线。
- [网页牌桌说明](web/README.md)：介绍本地启动方法和当前网页能力。
- [神经网络训练说明](neural/README.md)：介绍 GPU 训练、导出、校验和对战命令。

## 当前功能

正式参赛 AI 位于 `submission.js`，入口为：

```js
function act(view) { /* 返回一个平台允许的动作对象 */ }
```

当前策略是一套受固定计算预算约束、带轻量针对性的紧凶型策略，主要包括：

- 六人桌各位置的开池、防守、3-bet 和 4-bet 范围；
- 七张牌牌型判断；
- 同花、顺子连接性、牌面对子的结构分析；
- 根据对手数量动态调整的确定性蒙特卡洛预算；
- 根据对手行动缩窄其可能手牌范围，而不是始终按完全随机手牌计算；
- 对弃牌、跟注和不同下注尺寸进行近似期望收益比较；
- 综合底池赔率、SPR、多人底池和对手弃牌倾向；
- 使用贝叶斯平滑处理 VPIP、PFR 和动作频率等小样本统计；
- 最终合法性保护层，保证返回平台允许的动作。

训练和参数搜索放在离线环境完成。正式提交的 `act(view)` 只执行有限次查表、抽样和算术运算，不依赖网络、外部模型、系统时间或无限优化循环。

项目还保留一条独立的实验路线：用范围约束的蒙特卡洛教师生成标签，训练 `32→64→32→4` 的 PyTorch 多层感知机，再把权重嵌入纯 JavaScript 文件 `submission_nn.js`。它不会覆盖现有 `submission.js`；完整命令见 [神经网络训练说明](neural/README.md)。

## 环境要求

- 正式提交文件：AGX 的 QuickJS 运行环境，无第三方依赖。
- 静态校验和模拟器：Python 3.10 或更高版本。
- JavaScript 行为测试：Node.js。
- 网页牌桌：现代浏览器和任意静态文件服务器。

## 运行校验

执行正式提交文件的静态与契约检查：

```bash
python3 tools/validate.py
python3 tools/competition_rules.py

# 训练并导出后校验神经网络版本
python3 tools/validate.py submission_nn.js
```

在安装了 Node.js 的机器上执行牌型、策略行为、合法动作和性能冒烟测试：

```bash
node tests/test_submission.js
node tests/test_competition_constraints.js
node tests/test_simulator.js
python3 tests/test_experiment_registry.py
python3 tests/test_exact_engine.py
```

## 实验登记

蒸馏实验使用唯一编号和固定字段登记。创建、完成、上线与一致性检查命令见 [扑克蒸馏工作区说明](poker-distill/README.md)。空登记表可直接检查：

```bash
python3 tools/experiment_registry.py check
python3 tools/experiment_registry.py list
python3 tools/environment_gate.py status
```

## 运行离线模拟器

```bash
python3 simulator/simulate.py --hands 6000 --seed 7607
python3 simulator/simulate.py --hands 30000 --seed 7607 --candidate tag --opponents mixed
```

运行精确规则引擎的随机状态机压力测试：

```bash
python3 poker-distill/simulator/stress.py --hands 100000 --seed 7607 \
  --report poker-distill/reports/engine_stress_100k.json
```

`simulate.py` 是快速的 Python 近似基准，不直接执行正式提交文件。

使用 Node.js 直接让当前 `submission.js` 对战优化前基线：

```bash
node simulator/simulate_submission.js --matches 10 --seed 7607
```

直接模拟器会为六名固定参赛者创建相互隔离的 AI 运行环境，复用40组牌序并完成六轮换座，同时输出净额、mbb/手、第一名份额、动作分布、非法动作、超预算次数，以及平均、P50、P95、P99和最坏决策耗时。

两个模拟器都属于本项目的开发基准，并不声称与 AGX 私有比赛引擎逐字节一致。

## 启动网页牌桌

```bash
cd web
python3 -m http.server 4173
```

然后访问 `http://localhost:4173`。

公开版本：[AGX Poker Lab](https://agx-poker-lab.rockyfinch129.chatgpt.site)

网页目前使用独立的浏览器本地 AI 策略。将网页的五个对手全部切换为正式 `submission.js` 决策接口，已经记录在 [TODO.md](TODO.md) 中。

## 提交流程

1. 修改 `submission.js`。
2. 运行 `python3 tools/validate.py`。
3. 运行 `node tests/test_submission.js`。
4. 使用相同牌序比较新旧策略的净额、mbb/手、第一名率和最坏耗时。
5. 只有在收益改善且没有增加非法动作或超时风险时，才保留新版本。
6. 将最新验证通过的 `submission.js` 原样上传到 AGX。

已经冻结的 AGX 对局会继续使用当时的提交版本。平台的合法动作定义、资源限制和最终计分规则始终优先于本项目的近似模拟结果。
