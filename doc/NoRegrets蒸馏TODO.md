# NoRegrets 六人扑克教师蒸馏 TODO

> 目标：使用公开的 NoRegrets/Pluribus 风格实现，在本地训练属于本项目的六人 100BB 蓝图策略；再把蓝图输出的动作分布与价值信号蒸馏进满足 AGX 运行限制的轻量 JavaScript 学生。
>
> 这条路线是“公开代码训练教师 → 查询教师 → 蒸馏学生”，不是下载或冒充官方 Pluribus 权重。公开仓库不提供可直接使用的强蓝图权重，教师强度必须由我们自己的训练和评测证明。

## 0. 路线边界与成功定义

- [x] 比赛规则、回放解析器、模拟器和部署限制以 [`蒸馏TODO.md`](./蒸馏TODO.md) 为唯一事实源。
- [x] 使用公开实现只作为离线教师；最终提交不得访问网络、外部文件或启动求解器。
- [x] 不把 NoRegrets、Pluribus 风格或 CFR 标签自动等同于 GTO。
- [x] 不使用未获授权的商业权重、私有蓝图或泄漏的模型文件。
- [x] 保留现有正式 `submission.js`，新路线通过全部门禁前不得替换。
- [x] 确认比赛规则允许使用公开源代码训练得到的离线教师，并在方法说明中如实披露。
- [x] 固定 NoRegrets 上游仓库 URL、Git commit、许可证文件哈希和获取日期。
- [x] 记录对上游源码做过的全部修改；优先通过适配层集成，避免不可审计的直接改写。

实现状态：方法与合规披露见 [`NoRegrets方法说明.md`](./NoRegrets方法说明.md)。公开上游已固定到 `757f7692738069522195d2b486eec60a8b010c0c`（2026-10-20 获取）；用户已于 2026-10-20 确认主办方允许公开源码离线教师。规则适配补丁单独保存在 `tools/noregrets/patches/`，不静默改写来源版本。

成功至少同时满足：

1. 教师环境与 AGX 六人 100BB 规则的关键语义一致。
2. 教师能稳定输出合法的混合动作概率，且相同输入与种子可复现。
3. 学生在未见教师状态上的 policy KL、动作 regret 和价值误差达到预设门槛。
4. 学生通过 JavaScript 合法性、速度、内存和源码大小门禁。
5. 在同牌序 paired evaluation 中，学生对当前正式版本有统计可信的提升；否则保留为研究分支。

---

## 1. 上游审计与可复现安装

固定上游：<https://github.com/conorarmstrong/noregrets>，精确版本与审计结果见 `poker-distill/teachers/noregrets/manifest.json`。

- [x] 将 NoRegrets 克隆到服务器独立的第三方目录，不把完整上游仓库直接提交到本仓库。
- [x] 固定上游 commit，不跟随浮动的 `main`。
- [x] 保存 `LICENSE`、README、依赖版本、编译器版本和构建命令。
- [x] 检查许可证是否覆盖源码修改、离线训练、模型产物和比赛提交场景。
- [x] 检查仓库是否存在非开源子模块、商业权重入口或需要额外许可的数据。
- [x] 建立 `tools/noregrets/` 适配层，所有补丁和数据转换都进入版本控制。
- [x] 建立 `poker-distill/teachers/noregrets/manifest.json`，记录上游、配置、种子、构建产物哈希和训练产物哈希。
- [x] 写一键环境检查，只做版本与依赖验证，不自动开始长时间训练。

实现状态：服务器 checkout 位于 `/userhome/cs5/u3680889/third_party/noregrets`，使用 detached HEAD；公开仓库无 Git 子模块和预训练蓝图，商业产物被显式禁止。全部上游修改均作为独立补丁保存在 `tools/noregrets/patches/`。比赛许可、源码、工具链、补丁栈及 release 二进制均已通过 `check_environment.py require`；当前二进制 SHA-256 为 `b514f128ad5dfeeba14f0800b392fff9016d345fb23a2aa4322f99ee7cae5bd6`。

建议目录：

```text
第三方源码（服务器、Git 忽略）
  third_party/noregrets/

本仓库（纳入 Git）
  tools/noregrets/
    check_environment.py
    export_queries.py
    validate_teacher.py
  poker-distill/teachers/noregrets/
    README.md
    config/
    manifests/
  poker-distill/reports/
    noregrets_*.json

大型产物（服务器、Git 忽略）
  poker-distill/data/noregrets-blueprints/
  poker-distill/data/noregrets-queries/
```

门禁 `NG-1`：无法固定许可证、commit、依赖或训练配置时停止，不进入训练。

---

## 2. 精确映射 NoRegrets 与 AGX 规则

### 2.1 必须逐项核对

- [x] 玩家数固定为 6。
- [x] 初始筹码为 10,000，SB/BB 为 50/100，即 100BB。
- [x] 无前注。
- [x] 每手筹码独立重置，不把现金局筹码跨手累积。
- [x] 按钮、盲注、行动顺序与 AGX 一致。
- [x] `fold/check/call/bet/raise/all-in` 的合法性一致。
- [x] `raise to` 与“额外加注额”的语义完成显式转换。
- [x] 最小加注、短码 all-in 后是否重新开放加注与 AGX 一致。
- [x] 主池、边池、无人跟注筹码退回和平分余数规则一致。
- [x] NoRegrets 的下注抽象覆盖我们关心的翻前与翻后尺度。
- [x] 明确 NoRegrets 是否能表达多人仍在池中的翻后状态，不能表达的状态不得伪造教师标签。

实现状态：审计表见 `poker-distill/teachers/noregrets/RULE_MAPPING.md`。固定上游原版在短全下重新开放和平分余数上与 AGX 不同，已通过两份可审计补丁修正并应用到服务器 checkout。计算节点 `cargo test --release` 通过 137/137，补丁后 release 二进制 SHA-256 为 `e6535c16dfc1002540936aaa06cf5d2e0dfe64a99396b8ae4f85f695babd5ec4`。

### 2.2 状态转换器

- [x] 定义 AGX 决策 JSONL 到 NoRegrets 公共状态的无损/有损字段映射表。
- [x] 使用规范化座位顺序，避免物理座位编号产生策略泄漏。
- [x] 使用花色同构标准化，并保存正向与反向映射测试。
- [x] 将历史下注转换成 NoRegrets 的动作抽象；记录无法精确映射的状态。
- [x] 输出转换质量字段：`exact`、`projected`、`unsupported`。
- [x] 对 `projected` 状态记录下注尺度误差；`unsupported` 状态禁止训练。
- [x] 确保 `can_raise` 使用实时合法动作推导或显式字段，防止再次发生训练/部署漂移。
- [x] 对同一状态做 AGX → NoRegrets → AGX 往返测试。

### 2.3 一致性测试

- [x] 从已验证的 300 场 Top-20 回放中分层抽取至少 10,000 个状态。
- [x] 覆盖翻前、翻牌、转牌、河牌，单挑和多人底池。
- [x] 覆盖 check、call、普通加注、短码 all-in 和不能再次加注状态。
- [x] 状态转换零崩溃、零非法动作、零 NaN。
- [x] 对可精确表达的状态，合法动作集合完全一致。
- [x] 报告各街与各底池人数的 `exact/projected/unsupported` 比例。

实现状态：固定种子 7607 对 Top-20 的 151,570 个决策按“街道 × 单挑/多人”分层抽取 10,000 个状态，结果为 `exact=1,709`、`projected=8,162`、`unsupported=129`，零崩溃、零 NaN、精确状态合法动作零不一致；覆盖 156 个全下、9 个短全下和 187 个不能加注状态。报告为 `poker-distill/reports/noregrets_mapping_audit_10000.json`，映射完整性门禁通过；后续查询必须过滤全部 `unsupported`。

门禁 `NG-2`：只允许对映射正确且教师原生支持的状态生成标签；不以静默默认值填补缺失语义。

---

## 3. 先做最小教师冒烟，不直接大训练

- [x] 在 CPU 计算节点上完成构建；不在登录节点运行训练。
- [x] 用固定种子运行最小规模训练，例如 1–5 百万次迭代或上游支持的更小冒烟规模。
- [x] 保存完整 stdout/stderr、墙钟时间、峰值内存、CPU 核数和退出码。
- [x] 验证 checkpoint 可以保存、重新加载并继续训练。
- [x] 验证相同 checkpoint 对同一状态输出确定且归一化的动作概率。
- [x] 验证所有非法动作概率为 0，合法动作概率和为 1。
- [x] 验证教师至少不是退化策略：不能长期只输出 fold、call 或 all-in。
- [x] 用小规模自博弈和固定基线检查收益、动作分布及异常率。
- [x] 估算正式训练需要的 CPU 小时、内存和磁盘，再决定 Slurm 资源。

实现状态：`NG-3` 已通过。Slurm 作业 `137774` 在计算节点 `gpu-4080-401` 以 4 CPU（未使用 GPU）完成固定种子 7607 的 100 万次迭代训练，并从 checkpoint 继续至 110 万次迭代。1,000 手确定性自博弈覆盖 8,903 个决策，跨进程输出一致，非法动作概率质量为 0，最大归一化误差为 `3.33e-16`；动作概率占比为 fold 36.51%、check/call 36.50%、普通 raise 16.72%、all-in 10.27%，未退化。100 万次训练墙钟 84.0 秒、峰值 RSS 4.21 GiB；按观测速率线性外推 2 亿次约 4.15 墙钟小时 / 16.60 CPU 小时。正式单种子暂按 4 CPU、16 GiB、8 小时、12 GiB 磁盘规划；三种子至少预留 40 GiB，而运行前 home 仅余约 22 GiB，因此第 4 部分启动前必须扩容或选择获准的大容量产物盘。完整日志及大型产物保存在服务器，版本库摘要见 `poker-distill/reports/noregrets_smoke_1m.json`。本次 smoke 只验证工程链路，不得作为学生标签来源。

冒烟训练不是强教师，只验证工程链路。它产生的标签不得直接晋级正式学生。

门禁 `NG-3`：checkpoint 重载、查询确定性、概率合法性或资源预算任一失败时，不开始正式训练。

---

## 4. 正式蓝图教师训练

### 4.1 训练计划

- [ ] 先复现上游 README 给出的标准配置和一个可比较的训练曲线。
- [x] 建立 AGX 六人 100BB 配置，显式保存全部下注抽象。
- [x] 至少训练 3 个不同随机种子的蓝图，防止单次训练偶然性。
- [x] 按固定间隔保存 checkpoint，禁止只保留最终模型。
- [x] 记录每个 checkpoint 的迭代数、平均 regret/上游指标、大小和 SHA-256。
- [x] 每个 checkpoint 都跑固定教师评测集，避免只看训练内部指标。
- [x] 如果上游实现只训练 blueprint，不支持安全的实时搜索，则明确只使用 blueprint。
- [x] 如果加入搜索，单独记录搜索深度、迭代数、随机种子和耗时，不把它混入蓝图版本号。

正式训练 v1 采用资源受限方案：配置固定在 `poker-distill/teachers/noregrets/config/blueprint-formal-v1.json`，保留上游 README 的六人 100BB、12 buckets、Pluribus menu、200 rollouts、24 runouts 和 30,000 k-means samples，但将每个种子的迭代上限从 2 亿调整为 1 亿。种子固定为 7607、17607、27607；单个 Slurm 作业顺序训练三个种子，避免 QOS 并发限制。每 2,000 万次形成可恢复边界，每个种子只保留最近 3 个 zstd 压缩 checkpoint；仍记录压缩前后 SHA-256、吞吐、infoset 数、峰值内存、概率合法性和固定 random/caller 评测。最终蓝图只包含纯 blueprint，不启用在线搜索，并在导出后删除未压缩的当前 checkpoint。作业中断后以相同命令重提，runner 会从最后一个保留并成功登记的 checkpoint 继续。训练完成只进入 `trained_pending_ng4_evaluation`，不会自动开放教师查询或学生训练。

初始启动记录（2026-10-21）：Slurm 作业 `137791` 曾在 `batch` 分区的 `gpu-4080-402` 节点按旧配置哈希 `6a2db840098bf772cd6e0b7c0917ddb79607126c37b999e36ee6199c55ee56c0` 启动种子 7607 的首个 2,000 万次区间。集群 QOS 强制 batch 作业申请 GPU；NoRegrets 训练本身不调用 GPU，该资源仅用于满足调度要求。作业号与输出目录固定写入状态文件，后续不得把“分配了 GPU”误记成“使用 GPU 加速训练”。

恢复记录（2026-10-21）：作业 `137791` 完成种子 7607 的首个 2,000 万次 checkpoint 后，在继续至 4,000 万次时触发 Slurm OOM（退出码 137）。首阶段峰值 RSS 已达 15.38 GiB，原 16 GiB 请求没有增长余量；2,000 万次的原始及压缩 checkpoint、验证和评测均完整保留。batch 分区限制每 CPU 最多申请 10 GiB，且每张 GPU 绑定 4 CPU，因此恢复作业必须申请 2 GPU / 8 CPU 才能获得 64 GiB 内存；训练配置仍固定为 4 个 Rayon 线程，GPU 不参与计算，额外 CPU/GPU 只用于满足调度器的资源绑定与内存配额。恢复从已登记的 2,000 万次 checkpoint 开始；失败阶段的 `.stage.bin` 已删除且不作为 checkpoint。

恢复作业 `137810` 在 `gpu-4080-401` 上将种子 7607 从 2,000 万次继续训练至 1 亿次，累计形成 5 个已登记 checkpoint，未重新训练首阶段。1 亿阶段峰值 RSS 约 51.9 GiB；结合当前 64 GiB 作业内存上限及剩余磁盘，继续执行原定每种子 2 亿次没有安全余量，因此在完整登记 1 亿 checkpoint 后主动取消作业，没有把取消时的 1.2 亿 `.stage.bin` 视为有效产物。资源受限配置通过旧配置哈希兼容列表接续已有进度：种子 7607 只执行零增量最终蓝图导出、验证与滚动清理，不重复训练；其余两个种子各训练至 1 亿次。上游 2 亿次标准曲线仍未复现，4.1 第一项保持未完成。

资源受限恢复作业 `137812` 已使用新配置哈希 `f35e5938e72b3551162c602c6eab8e1487e8ea6489de5ad8461d3fa4aead5c1a` 启动。runner 已完成旧进度迁移，为种子 7607 从 1 亿 checkpoint 导出并验证 `blueprint-final.bin`，将其 gate 更新为 `trained_pending_ng4_evaluation`，删除未压缩 checkpoint，并只保留 6,000 万、8,000 万和 1 亿三个压缩恢复点；随后已进入种子 17607 的训练。正式总 gate 仍为 `running`，直到三个种子均达到 1 亿并完成验证。

### 4.2 教师自身评测

- [ ] 与 NoRegrets 自带基线/历史 checkpoint 对战。
- [x] 与本项目 TAG、Calling Station、Mixed 和当前正式版本对战。
- [x] 使用相同牌序与座位轮换进行 paired evaluation。
- [x] 分街统计动作分布、平均下注尺度和 all-in 频率。
- [x] 分单挑/多人底池统计，重点检查多人翻后是否异常激进。
- [x] 检查最差 5% 对局、第一名率、平均名次和非法动作率。
- [x] 不以单一 `mbb/hand` 或短样本胜负认定教师强度。

门禁 `NG-4`：蓝图必须显著优于退化/弱基线，且不存在明显动作分布异常，才可作为正式教师。

NG-4A 实现状态（2026-10-21）：已新增 `poker-distill/teachers/noregrets/config/ng4-eval-v1.json` 与可恢复 runner `tools/noregrets/run_ng4_evaluation.py`。作业 `137850` 已完成每种子 10,000 手确定性/合法性审计、对 random/caller 各 120,000 手相同牌序六座轮换 duplicate evaluation，以及全部六个有向种子组合各 100,000 手 crossplay。三个种子的非法动作概率质量、无效概率向量和确定性不一致均为 0；动作概率份额稳定在 fold 58.23%–58.30%、check/call 18.91%–19.15%、raise 16.55%–16.72%、all-in 6.06%–6.09%。对 caller 的最差 `mbb/hand - CI95` 为 +2051.1，对 random 为 +4679.7，弱基线显著性门禁通过；六项 crossplay 均覆盖 0，未发现统计可信的种子间不兼容。报告为 `poker-distill/reports/noregrets_ng4a_v1.json`，SHA-256 为 `ce132ee69c6401df8f56efdc62c940652ecd8ceeb079766a6cc7f98dcf28d418`。当前 gate 为 `phase_a_passed_pending_project_baselines`，`full_ng4_approved=false`；TAG、Calling Station、Mixed 和当前正式 JavaScript 策略评测完成前，完整 NG-4 仍保持未通过。

NG-4B 实现状态（2026-10-21）：已通过持久 JSON Lines 桥接器将三份正式蓝图接入项目 Node.js 六人模拟器；作业 `137870` 对每个“训练种子 × 对手”组合运行 30 个完整 240 手 paired match，共 12 组、86,400 个候选手次。全部组合均为零非法动作、零查询超时，并保存分街、单挑/多人、下注尺度、最差 5%、第一名率和平均名次统计。三个种子对 Calling Station 与 Mixed 的 95% 收益下界均为正；但对 TAG 的下界分别为 -1437.3、-1658.3、-1384.3 mbb/hand，对当前正式版本的下界分别为 -2391.3、-2264.6、-2230.5 mbb/hand。完整 `NG-4` 因此明确失败，`full_ng4_approved=false`，不得进入第 5 节教师标签导出。报告为 `poker-distill/reports/noregrets_ng4_project_v1.json`，SHA-256 为 `33bb37e26415e1bbf23f693d14514a4041f9e6564cd58462656ac4dac2bb3c1e`。首次作业 `137863` 暴露并保留了短码 all-in/canRaise 语义诊断，修复后才执行正式作业；无效结果未用于强度判定。

NG-4C 诊断结论（2026-10-21）：作业 `137873` 完成 12 组有向项目基线矩阵及 12 组“三种子 × 两种按街混合 × TAG/当前版本”筛查，每组 10 个完整 240 手 match，共 57,600 个候选手次，全部零非法动作、零超时。TAG 与当前正式版本近似同档：当前版本对 TAG 为 -26.8 mbb/hand（95% 下界 -156.1），TAG 对当前版本为 +105.6（下界 -7.7），两个方向均不能证明显著优势，排除了 TAG 基线异常偏强的解释。仅让 NoRegrets 负责翻前时，12 项中的六个相关组合点估计全部为负，且对当前版本的三个 95% 下界为 -1290.4、-1965.2、-2046.1；保留当前翻前、只让 NoRegrets 负责翻后虽明显缩小对 TAG 的差距，但对当前版本仍为 -967.6、-818.2、-481.4 mbb/hand，三个下界均低于 -1100。由此判定损失同时存在于翻前和翻后，翻前更严重；当前 1 亿迭代蓝图不再作为 v1 主要教师继续投入，也不通过局部按街路由绕过 NG-4。报告为 `poker-distill/reports/noregrets_ng4c_diagnostic_v1.json`，SHA-256 为 `5642b30f80f3a84b37300ddadb4d78ce6a86479f5d6f41a0e1520e2470b72423`。如未来重新开启此路线，必须使用独立新版本配置并从 NG-4 重新过门禁；现阶段转回 Top-K 行为教师、当前正式策略和困难状态 DAgger。

---

## 5. 教师查询与软标签导出

### 5.1 查询状态来源

- [ ] 已验证 Top-20 回放训练集：提供真实天梯分布。
- [ ] 当前学生自博弈到达状态：提供部署分布。
- [ ] `round_1` 的 10,000 个困难状态：修复现有学生错误。
- [ ] 蓝图自博弈状态：覆盖教师自然到达分布。
- [ ] 人工边界状态：覆盖短 all-in、极端 SPR、边池及不能加注等稀有节点。
- [ ] 以完整 `match_id` 或生成轨迹划分 train/validation/test，禁止状态近邻泄漏。

### 5.2 每条标签必须包含

```json
{
  "teacher": "noregrets-blueprint",
  "teacher_version": "commit+config+checkpoint-sha",
  "source": "top20|student-rollout|hard-state|teacher-selfplay|edge-case",
  "state_hash": "...",
  "mapping_quality": "exact|projected",
  "legal_mask": [1, 1, 1, 0, 0, 1, 0, 0, 0, 1],
  "policy": [0.1, 0.0, 0.6, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0, 0.1],
  "action_values": null,
  "state_value": null,
  "query_seed": 7607
}
```

- [ ] 保留教师原始动作概率，不先压成 argmax 硬标签。
- [ ] 将教师下注动作映射到本项目 10 动作桶，并记录投影误差。
- [ ] 对多个教师动作落入同一学生桶时求和，不覆盖。
- [ ] 重新施加 AGX 合法动作掩码并归一化。
- [ ] 如果 NoRegrets 只输出策略、不输出可信动作 EV，则 `action_values` 保持空值；禁止伪造 regret 标签。
- [ ] 区分教师 state value、Monte Carlo 回报和动作 EV，三者不能混用。
- [ ] 保存查询工具版本、输入数据哈希、输出标签哈希和失败清单。
- [ ] 抽样人工审计至少 200 条标签。

### 5.3 教师集成策略

- [ ] NoRegrets 标签第一轮单独训练，先测清其独立贡献。
- [ ] 第二轮再与 Top-20 行为标签融合。
- [ ] 对 `exact` 映射赋正常权重，对 `projected` 映射降权。
- [ ] 对教师种子/蓝图之间分歧大的状态降低权重，并保留混合概率。
- [ ] 多人翻后若教师支持或质量不足，回退到已验证行为教师或正式启发式策略。
- [ ] 旧 `equity-ev-proxy-v1` 已被审计为过度进攻，不与 NoRegrets 标签混合。

门禁 `NG-5`：标签动作分布、合法性、映射误差和教师分歧报告通过后，才可进入学生训练。

---

## 6. 学生蒸馏实验

### 6.1 第一轮：纯 NoRegrets 策略蒸馏

- [ ] 复用现有无身份、无赛后泄漏的状态编码。
- [ ] 输入维度变化时更新 Python/JavaScript 双端特征一致性测试。
- [ ] 使用合法动作掩码后的 policy KL 作为主损失。
- [ ] 对软标签使用温度校准；保存原始与校准后的 KL/ECE。
- [ ] 只有教师确实输出可信价值时才启用 value MSE。
- [ ] 只有教师确实输出可信动作 EV 时才启用 regret loss。
- [ ] 分别训练 3 个随机种子，报告均值和方差。
- [ ] 记录实验注册表、数据哈希、教师 checkpoint 哈希和模型哈希。

第一轮默认损失：

```text
L = 1.00 * policy_KL
  + 0.00 * value_MSE       # 有可信 value 后再开启
  + 0.00 * regret_loss     # 有可信 action EV 后再开启
  + 0.05 * calibration_loss
```

### 6.2 第二轮：混合教师

- [ ] 比较 `NoRegrets only`、`Top-20 only` 和 `NoRegrets + Top-20`。
- [ ] 按街道分别搜索教师权重，不使用全局单一比例掩盖差异。
- [ ] 按单挑/多人底池分别搜索教师权重。
- [ ] 保留当前启发式策略作为安全回退和独立对照。
- [ ] 对现有困难状态单独报告策略 KL、动作一致率和高代价错误。

建议从保守网格开始：

```text
preflop:       NoRegrets 0.75 / Top-20 0.25
postflop HU:   NoRegrets 0.60 / Top-20 0.40
postflop multi:仅在教师多人支持通过审计后启用；否则行为教师/启发式回退
```

这些比例只是待验证的实验起点，不是预设结论。

### 6.3 DAgger

- [ ] 用第一轮学生对战完整对手池并收集实际到达状态。
- [ ] 查询 NoRegrets 教师重新标注低置信度、高损失和分布外状态。
- [ ] 完成至少 3 轮，分别保存每轮新增状态和教师版本。
- [ ] 每轮都与上一轮做同牌序评测；收益不增加时停止。

---

## 7. 离线与实战晋级门禁

### 7.1 教师拟合指标

- [ ] validation/test policy KL。
- [ ] 动作族准确率与 macro-F1。
- [ ] 下注桶准确率及下注尺度投影误差。
- [ ] Expected Calibration Error。
- [ ] 按街道、位置、单挑/多人、SPR 和 `can_raise` 分桶报告。
- [ ] 困难状态子集单独报告，不允许总体均值掩盖失败。

### 7.2 游戏评测

- [ ] 快筛至少 200 局（48,000 手）。
- [ ] 正式对照至少 2,000 局（480,000 手）。
- [ ] 最终确认至少 10,000 局（240 万手）。
- [ ] 全部使用相同牌序、座位轮换和 paired bootstrap 95% 置信区间。
- [ ] 对手池同时包含当前正式版、官方基线、行为克隆及风格化策略。
- [ ] 报告 `mbb/hand`、第一名率、平均名次、OpenSkill 代理、尾部损失和各位置收益。
- [ ] 候选若只优于弱基线但不优于当前正式版，不晋级。

### 7.3 部署安全

- [ ] 导出单文件 JavaScript，模型与查表全部内嵌。
- [ ] 10 万次动作调用零异常、零非法动作。
- [ ] 1,000 局零 timeout、零 forfeit、零离场。
- [ ] p99 动作耗时低于 10ms，整局 CPU 低于 8–10 秒。
- [ ] 源码低于 3.5MB，给平台上限保留余量。
- [ ] Python 与 QuickJS 的特征、mask、logits、概率和最终动作逐层对齐。

门禁 `NG-6`：只有正式 paired evaluation 的主要目标优于当前正式版本，且无安全回归，才允许生成待提交候选。

---

## 8. 实验编号建议

| 实验 | 内容 | 目的 |
|---|---|---|
| `E10_noregret_smoke` | 最小蓝图训练与查询 | 验证完整工程链路 |
| `E11_noregret_blueprint_s1` | 正式蓝图，种子 1 | 建立教师基线 |
| `E12_noregret_blueprint_s2` | 正式蓝图，种子 2 | 检查教师方差 |
| `E13_noregret_blueprint_s3` | 正式蓝图，种子 3 | 检查教师方差 |
| `E14_noregret_student` | 纯 NoRegrets policy KL | 测量独立教师价值 |
| `E15_noregret_behavior_mix` | NoRegrets + Top-20 | 搜索混合教师权重 |
| `E16_noregret_dagger_r1` | 第一轮部署分布回标 | 修复学生到达状态 |
| `E17_noregret_dagger_r2` | 第二轮部署分布回标 | 检查边际收益 |
| `E18_noregret_js_candidate` | 量化与 JS 候选 | 完成部署门禁 |

---

## 9. 失败条件与回退策略

- [ ] 若 NoRegrets 无法正确表达 AGX 多人翻后状态，只将其用于经过验证的翻前或单挑子域。
- [ ] 若下注抽象映射误差过大，先调整抽象或缩小适用域，不强行生成标签。
- [ ] 若蓝图自身不优于当前启发式策略，停止大规模标签导出。
- [ ] 若学生能拟合教师但实战变差，检查教师质量、数据分布、动作投影和价值目标，不以继续加 epoch 掩盖问题。
- [ ] 若教师查询成本过高，优先标注困难状态与学生实际到达状态，而不是无差别扩充数据。
- [ ] 若许可证或比赛规则存在不确定性，保留研究产物但不提交线上。
- [ ] 任何阶段失败都回退到当前正式 `submission.js`，不影响已验证提交。

---

## 10. 当前立即执行的前五项

- [ ] 审计并固定 NoRegrets 上游 URL、commit 和许可证。
- [ ] 在服务器建立 Git 忽略的第三方源码与蓝图产物目录。
- [ ] 写环境检查与可复现构建说明，记录实际依赖版本。
- [ ] 完成 AGX ↔ NoRegrets 规则/状态/动作映射表。
- [ ] 在 CPU 计算节点运行最小训练、checkpoint 重载和教师查询冒烟。

完成这五项并通过 `NG-1` 至 `NG-3` 后，再申请正式 CPU 训练资源；目前不应直接启动大规模蓝图训练。
