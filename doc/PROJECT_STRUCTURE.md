# 项目结构说明

本文档说明 `agx-poker-bot` 中每个目录和文件的作用。

```text
agx-poker-bot/
├── .gitignore
├── README.md
├── config/
│   └── competition.json
├── doc/
│   ├── PROJECT_STRUCTURE.md
│   ├── TODO.md
│   └── 蒸馏TODO.md
├── submission.js
├── submission_nn.js                 # 训练并导出后生成，不提交大权重产物
├── baselines/
│   └── submission_v1.js
├── neural/
│   ├── README.md
│   ├── data.py
│   ├── train.py
│   ├── export_submission.py
│   ├── submission_nn.template.js
│   └── artifacts/
│       └── .gitkeep
├── poker-distill/
│   ├── README.md
│   ├── data/
│   │   ├── raw-replays/
│   │   ├── parsed-decisions/
│   │   ├── solver-labels/
│   │   └── dagger/
│   ├── simulator/
│   │   ├── README.md
│   │   ├── engine.py
│   │   └── stress.py
│   ├── replay-parser/
│   │   ├── README.md
│   │   ├── download_replays.py
│   │   └── parse_replay.py
│   ├── teachers/
│   ├── student/
│   ├── runtime-js/
│   ├── evaluation/
│   ├── experiments/
│   │   ├── config.template.json
│   │   └── experiments.csv
│   ├── submissions/
│   └── reports/
├── simulator/
│   ├── simulate.py
│   └── simulate_submission.js
├── tests/
│   ├── fixtures/
│   │   └── slow_submission.js
│   ├── test_competition_constraints.js
│   ├── test_exact_engine.py
│   ├── test_experiment_registry.py
│   ├── test_submission.js
│   └── test_simulator.js
├── tools/
│   ├── competition_rules.py
│   ├── environment_gate.py
│   ├── experiment_registry.py
│   └── validate.py
└── web/
    ├── README.md
    ├── index.html
    ├── app.js
    ├── styles.css
    └── match.css
```

## 根目录

### `.gitignore`

定义不应提交到 Git 的本地缓存、临时文件和开发环境产物。

### `README.md`

项目入口文档，说明项目目标、当前 AI 策略、环境要求、运行命令、提交流程和相关文档链接。

### `config/competition.json`

唯一的比赛约束清单，冻结规则版本、桌型、盲注、初始筹码、换座阶段、上下文重置点、动作金额语义、资源限制、计分口径和部署依赖限制。

## `doc/`

### `doc/PROJECT_STRUCTURE.md`

当前文档。用树形结构维护项目文件清单，并解释各文件职责。

### `doc/TODO.md`

记录已经完成的功能、已知限制、后续任务、优先级和验收标准。开发完成一项任务后，应同步更新其中的复选框和说明。

### `doc/蒸馏TODO.md`

记录蒸馏与冲榜路线。第 0 节与 `config/competition.json` 对齐，并注明代码化约束的实现边界。

### `submission.js`

正式提交到 AGX 的单文件扑克 AI，公开入口是 `act(view)`。

主要职责包括：

- 读取平台提供的牌局视图；
- 评估七张牌牌型；
- 根据位置和行动历史选择翻前范围；
- 使用有限次蒙特卡洛抽样估计翻后胜率；
- 根据对手行动和历史统计估计其范围与弃牌倾向；
- 比较弃牌、跟注、下注和加注的近似期望收益；
- 将下注额限制在平台允许的范围内；
- 在异常情况下返回安全的合法动作。

该文件必须保持 QuickJS 兼容、零第三方依赖、无网络请求、无文件访问和无异步任务。

### `submission_nn.js`

执行神经网络导出命令后生成的实验提交文件。它包含完整网络权重和纯 JavaScript 前向推理，不依赖 PyTorch。该文件在训练前不存在，也不会自动替换正式 `submission.js`。

## `neural/`

### `neural/README.md`

神经网络路线的中文说明，包含服务器登录、`gpu-interactive`、`uv` 环境、冒烟训练、正式训练、导出与对战命令。

### `neural/data.py`

合成训练数据：随机生成六人桌局面，提取32维特征，通过范围约束蒙特卡洛估计胜率，并用底池赔率、SPR和近似EV教师产生四类动作标签。

### `neural/train.py`

PyTorch训练入口。模型为两层隐藏层的多层感知机，支持 CUDA 混合精度、类别权重、验证集、提前停止和训练报告输出。

### `neural/export_submission.py`

验证训练权重维度，把 `model.json` 嵌入 QuickJS 模板，并检查生成文件不超过4 MiB。

### `neural/submission_nn.template.js`

神经网络实验版的 QuickJS 运行时，负责复现32维特征、执行两层 ReLU 前向传播，并把四个输出类别映射为合法扑克动作。

### `neural/artifacts/`

训练数据、PyTorch检查点、JSON权重和训练报告的输出目录。除 `.gitkeep` 外默认被 Git 忽略，避免提交大文件。

## `baselines/`

### `baselines/submission_v1.js`

第一轮范围和EV优化之前的正式 AI 快照，仅用于回归测试和同牌序对照。该文件不作为当前提交版本继续开发。

## `poker-distill/`

蒸馏工作的统一目录树，分开放置回放、解析决策、求解器标签、DAgger 数据、教师、学生模型、JavaScript 运行时、评测、提交和报告。大型数据与提交产物默认被 Git 忽略。

### `poker-distill/experiments/`

保存每个唯一实验编号的配置快照和 `manifest.json`。`experiments.csv` 汇总 Git commit、数据版本、随机种子、教师、模型结构、损失权重、量化、模型哈希、离线结果和线上版本。

### `poker-distill/simulator/`

冻结到 `rsi-poker-4.1` 的精确规则状态机与十万手随机压力测试入口，覆盖累计下注目标、加注重开、退筹、边池、余数筹码和复式赛程。

### `poker-distill/replay-parser/`

包含公开回放下载器和完整轨迹解析器。解析器逐动作恢复状态、验证可选状态快照与最终净额、匿名化参与者，并输出统一 JSONL；缺少私有底牌时明确拒绝生成伪造标签。

## `simulator/`

### `simulator/simulate.py`

零依赖的六人配对牌局开发模拟器。

它会：

- 生成40组基础牌序；
- 让六名参赛者依次轮换六个物理座位；
- 组成每个240手的完整比赛块；
- 汇总固定参赛者编号的整数净额；
- 输出候选策略的净额、mbb/手和多个比赛块的近似置信区间。

当前模拟器使用简化的 Python 策略模型，还没有直接加载 `submission.js`，因此主要用于开发基准，而不是正式胜率证明。

### `simulator/simulate_submission.js`

直接执行正式 `submission.js` 的六人牌局引擎。它会：

- 为六名固定参赛者分别创建隔离的 Node.js VM，避免内存状态互相污染；
- 让当前候选策略对战指定的基线或对手文件；
- 运行40组牌序、六轮换座和每局240手；
- 执行盲注、四条下注街、合法动作、全下、边池、摊牌和平分底池；
- 对每手和完整比赛执行整数净额零和断言；
- 统计净额、mbb/手、第一名份额、动作分布和决策耗时分位数。

## `tests/`

### `tests/test_experiment_registry.py`

在临时目录中覆盖实验创建、重复编号拒绝、完成、线上版本登记、哈希计算以及 CSV/manifest 一致性检查。

### `tests/test_exact_engine.py`

覆盖本街累计 `to`、短全下与累计重开、退筹、主池/边池、平分余数、六阶段复式赛程，以及回放解析、状态快照、匿名化和收益核对。

### `tests/test_competition_constraints.js`

验证比赛约束清单中的冻结值、阶段重置点、资源上限和部署限制，并调用 Python 规则守卫确认审计版本没有漂移。

### `tests/test_submission.js`

正式 AI 的 Node.js 测试文件，覆盖：

- 基础牌型比较；
- A2345 等特殊顺子；
- 起手牌编码；
- 动态蒙特卡洛预算；
- 强牌再加注和弱牌弃牌行为；
- 河牌坚果牌价值下注；
- 300个翻前、翻牌和河牌混合动作的合法性；
- 下注额上下界；
- 粗粒度执行耗时回归。

### `tests/test_simulator.js`

直接提交模拟器的端到端冒烟测试。它会完整运行一场240手比赛，并确认：

- 进程正常结束；
- 没有非法动作或超预算动作；
- 输出 mbb/手和第一名份额；
- 正式 AI 可以被独立运行环境正常加载。

## `tools/`

### `tools/competition_rules.py`

加载并严格检查冻结的比赛约束。规则版本、审计状态或关键赛制参数发生变化时，训练、导出和校验会停止，等待重新审计。

### `tools/experiment_registry.py`

管理实验生命周期。创建实验时保存 Git 状态和配置快照，完成时计算模型 SHA-256 并登记结构化离线结果，上线后补充版本号；`check` 命令验证必填字段、唯一编号、配置哈希以及 CSV/manifest 一致性。

### `tools/environment_gate.py`

读取环境验收报告并阻止未经100局公开回放验证的大规模训练。验收前只允许显式添加 `--pipeline-smoke` 的不超过10,000样本流程测试。

### `tools/validate.py`

正式提交文件的静态与契约检查器。默认检查 `submission.js`，也可通过位置参数检查 `submission_nn.js`，负责确认：

- 文件大小没有超过限制；
- 存在 `act(view)` 入口；
- 没有 `require`、`import`、`fetch`、系统时间、异步函数或控制台输出；
- 代码中的动作名称属于允许集合。

它不负责评估策略强度。

## `web/`

浏览器内运行的真人参与牌桌，不需要后端服务。

### `web/README.md`

网页牌桌的中文使用说明，包括启动命令、比赛结构和当前限制。

### `web/index.html`

牌桌页面结构，包含比赛进度、六个座位、公共牌、底池、操作按钮、动作记录和结算弹窗。

### `web/app.js`

浏览器牌局引擎和交互逻辑，负责：

- 240手、六轮、每轮40手的比赛流程；
- 固定40组牌序和六轮换座；
- 每手10,000初始筹码；
- 盲注、四条下注街、弃牌、过牌、跟注、加注和全下；
- 边池、摊牌、平分底池和累计净额；
- 当前浏览器本地对手策略；
- 用户操作和界面渲染。

这里的对手策略目前独立于正式 `submission.js`，后续需要通过统一视图与动作适配层接入正式 AI。

### `web/styles.css`

网页的主要视觉样式，包括背景、牌桌、座位、扑克牌、按钮、日志、弹窗和响应式布局。

### `web/match.css`

240手比赛模式的补充样式，包括比赛进度条、阶段信息、累计净额和结算排名。

## 维护约定

新增、删除或移动文件时，应同时更新本文档的树形结构和对应说明。策略状态和开发计划发生变化时，应更新 `TODO.md`；运行方式或交付方式变化时，应更新根目录 `README.md`。
