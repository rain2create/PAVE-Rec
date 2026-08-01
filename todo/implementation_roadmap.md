# PAVE-Rec Implementation Roadmap
# PAVE-Rec 分阶段实施路线

## 1. 文档目的

本文档把当前研究设计转化为可逐步交付和验收的工程路线。

它不替代 01—10 模块设计文档，也不提前决定其中标记为 `TBD` 的研究问题。
每个阶段只实现支撑下一阶段所必需的最小能力，并保持研究策略可配置、可替换。

本文件属于活跃规划，不是已经确认的研究设计。当前只推进 Phase 1；其逐项
讨论和确认状态记录在 `todo/phase_1_discussion.md`。后续 Phase 在进入前分别
建立自己的 discussion 文件。

---

## 2. 总体实施原则

### 2.1 先跑通纵向闭环，再替换真实模型

第一条可运行路径必须覆盖：

```text
User Memory
+ Initial Ranking
→ Recommendation State
→ Information Need
→ Segment Value
→ Segment Perception
→ Evidence Update
→ Score Update
→ Rerank
→ Stop / Continue
```

这条路径首先使用 deterministic mock components。

### 2.2 Library API 是核心，CLI 是薄入口

Agent 的核心调用方式是 Python API：

```python
result = controller.run(
    AgentRunRequest(
        run_id=run_id,
        user_id=user_id,
        user_history=user_history,
        candidate_ids=candidate_ids,
    )
)
```

共享的 `run_from_config()` 负责：

- 读取配置
- 选择并组装组件
- 加载一次运行的输入
- 独占创建 run directory 并保存 resolved config
- 调用同一个 Controller Python API

CLI 只解析少量入口参数、调用 `run_from_config()` 并报告结果。Trace 和 Result
由 Controller 通过注入的 TraceWriter 写入，不在 CLI 中复制持久化流程。

CLI 不保存研究逻辑，也不实现另一套 Agent loop。

保留 CLI 的原因是让本地实验、服务器任务和论文复现实验拥有稳定入口。Notebook、
测试或其他 Python 程序可以绕过 CLI，直接调用相同的核心 API。

### 2.3 公共状态与模型实现分离

共享领域对象放在：

```text
src/pave_rec/domain/
```

具体模型、策略和外部服务不能反向污染领域对象。Agent Controller 依赖接口，
不依赖 SASRec、某个 MLLM 或某个 Value Model 的内部实现。

### 2.4 在线路径与离线路径分离

在线 Agent 只能读取已经准备好的序列、item features、segment metadata 和
segment proxies。视频切分、批量特征提取、Oracle 数据生成和训练属于离线流程。

### 2.5 每个阶段都必须可验收

“文件已经创建”不等于阶段完成。每个阶段需要具备：

- 明确输入输出
- 自动化测试
- 可复现运行方式
- 可检查的产物
- 已知限制和下一阶段边界

---

## 3. 阶段总览

```text
Phase 0  Repository Scaffold
   ↓
Phase 1  Deterministic Mock Agent Loop
   ↓
Phase 2  Offline Data and Feature Stores
   ↓
Phase 3  Real Cheap Path: User Memory + SASRec
   ↓
Phase 4  MLLM Evidence + Score-Update Baseline
   ↓
Phase 5  Oracle Data + Supervised Segment Value Model
   ↓
Phase 6  End-to-End Evaluation and Experiments
   ↓
Phase 7  Optional Advanced Research / RL
```

---

## 4. Phase 0 — Repository Scaffold

### 目标

建立稳定的源码、配置、数据、产物、实验和测试边界，不实现业务算法。

### 工作内容

- 建立 `pyproject.toml`
- 使用 `src/pave_rec` Python package layout
- 建立各功能模块的 package 边界
- 建立 `configs/`、`tests/`、`data/`、`artifacts/` 和 `runs/`
- 将设计文档集中到 `docs/`
- 配置 Git ignore，避免提交本地数据、模型和实验输出
- 在 README 中维护当前工程目录

### 交付物

- 可被 Python 发现的 `pave_rec` package
- 空实现但边界明确的功能 packages
- 数据和生成产物的目录说明
- 本实施路线文档

### 验收标准

- 目录结构与 README 一致
- 设计文档索引有效
- `pave_rec` 顶层 package 可以导入
- 本地数据、checkpoint 和 run outputs 默认不会进入 Git

### 当前状态

```text
Completed
```

---

## 5. Phase 1 — Deterministic Mock Agent Loop

### 目标

构建“最薄但完整”的 Agent 闭环，验证接口、状态转移、停止条件、日志和可复现性。

本阶段不追求模型效果。

### Research Decision Gate

Phase 1 开始编码前，必须先逐项完成 `todo/phase_1_discussion.md` 中的确认。
未确认事项只能保留为接口、Mock 或显式 `TBD`，不能根据实现便利自行决定。

### Step 1 — 定义核心领域对象

公共对象以 `docs/00_shared_domain_schemas.md` 的 canonical inventory 为准，
包括 references、User Memory View、initial ranking、segments、
Evidence/Observation、Recommendation State、Agent decisions、Trace 和 Result。
Memory 或模型内部的 `PreferenceAtom`、Tensor batch 等不属于公共 Domain Schema。

Trace、配置快照和最终结果必须可以稳定序列化。

### Step 2 — 定义组件接口

至少包括：

- `UserMemory`
- `InitialRanker`
- `ItemFeatureStore`
- `SegmentStore`
- `RecommendationStateBuilder`
- `InformationNeedEstimator`
- `SegmentValueModel`
- `SegmentPerceiver`
- `EvidenceUpdater`
- Observation transition owner / optional `ObservationUpdater`
- `ScoreUpdater`
- `StopPolicy`
- `TraceWriter`

接口定义应靠近相应功能模块，公共 schema 只在 `domain/` 中定义一次。

### Step 3 — 实现确定性 Mock Components

按照 `docs/00_deterministic_mock_scenario.md` 中已确认的 `mock-v1`，使用固定、
versioned fixture 实现。Canonical run 记录 seed，但不依赖 pseudo-random
behavior：

- Mock User Memory
- Mock Initial Ranker
- In-memory Item/Segment Stores
- Mock Information Need Estimator
- Mock Segment Value Model
- Mock Perceiver
- Mock Evidence Updater
- Mock Observation transition
- Mock Score Updater
- P1-06 已确认的 Phase 1 action-budget Stop Policy

Mock 必须能制造一次真实的排序变化，不能所有步骤都返回静态占位值。
主场景固定执行两次 perception：先观察 rank-2 的 `item_b.segment_1` 并触发
换位，再验证该 segment 不会被重复观察，最终使 perception budget 归零。

### Step 4 — 实现 Agent Runtime

按照 `docs/08_agent_controller.md` 中 P1-05 已确认的状态机实现：

- `AgentController`
- one-time initialization outside the decision loop
- Recommendation State rebuild
- pre-value stop before Information Need
- post-value stop before Perceiver
- segment observed 状态更新
- budget 和 step 更新
- normal failed-perception continuation
- terminal declared-exception handling
- deterministic `(item_id, segment_id)` value tie-break
- budget-derived hard loop guard
- reranking
- P1-07 chained full-State JSONL trace
- complete final `AgentRunResult`

### Step 5 — 配置、组装与运行入口

提供：

```text
configs/base.yaml
configs/mock.yaml
```

配置使用 P1-08 已确认的单父 `extends`、deterministic merge、PyYAML parse 和
strict/frozen Pydantic v2 validation；不引入 Hydra/OmegaConf 或动态 component
import。实现一个集中组装组件的 bootstrap/factory、共享 `run_from_config()` 和
薄 CLI：

```python
result = run_from_config("configs/mock.yaml")
```

```bash
python -m pave_rec.cli.run_mock --config configs/mock.yaml
```

每个 run 按 `docs/00_trace_replay.md` 生成：

```text
resolved_config.json
trace.jsonl
result.json
```

### Step 6 — 自动化测试

Unit tests：

- config/schema/path validation
- ranking uncertainty
- stop conditions
- evidence aggregation
- reranking
- score-update invariants
- trace/replay invariants
- partial-progress exception semantics
- composite `(item_id, segment_id)` identity and canonical collection ordering

Integration / E2E tests：

- 完整 mock loop
- zero-budget run
- no-unobserved-segment run
- stop after sufficiently high ranking margin
- stop after low maximum segment value
- deterministic replay
- exact deterministic Mock re-execution
- Perceiver/Updater/ScoreUpdater/TraceWriter failure paths
- Controller one-time initialization component-failure path
- config/bootstrap/runner/CLI equivalence
- golden resolved config、trace 和 result comparison

P1-09 已确认 Phase 1 quality gate：pytest 全部通过、Phase 1 implementation
modules 的 branch coverage 至少 90%，并通过 Ruff lint/format check。GitHub
Actions 必须覆盖 Ubuntu Python 3.10/3.12 和 Windows Python 3.12。测试必须
offline、CPU-only，并在 pytest 临时目录中建立 synthetic project root；配置的
fixture/output paths 仍保持在该 root 内，不放宽 P1-08 path rules。Golden
artifacts 使用 P1-07 canonical UTF-8/LF JSON serialization 和固定 collection
ordering。

### 第一里程碑输出

```text
initial ranking
→ information need
→ selected segment
→ mock evidence
→ updated scores
→ reranking
→ stop reason
→ final ranking
→ complete JSONL trace
```

### 验收标准

- 同一输入、配置和 seed 得到相同结果
- segment 不会被重复观察
- 每次 Perceiver attempt（成功或失败）恰好扣减一次 action budget
- 未观察 item 始终保留有意义的 initial ranking prior
- 每一步都重新构造完整 Recommendation State
- 每次退出都有明确 stop reason
- JSONL trace 足以回放一次 Agent 决策
- Controller 不依赖任何具体模型内部实现
- canonical golden artifacts 可以精确复现
- 所有正常 failure 和 declared exception 的 partial-progress 语义符合契约
- 本地 pytest/coverage/Ruff gates 和 GitHub Actions matrix 全部通过
- 测试不污染仓库 `runs/`，也不调用网络、GPU 或真实 MLLM

### 本阶段明确不做

- 真实 SASRec 训练
- 真实视频切分
- MLLM API 调用
- 最终 Information Need 公式
- 最终 Segment Value 架构
- 最终 Score Update 架构
- RL

### 当前实现状态 — `Completed`

Phase 1 已完成实现，包括 strict/frozen schemas、13 个显式组件、Controller、
配置继承、fixture loader、canonical artifacts、saved-output replay、CLI、golden
fixtures 和分层测试。本地 pytest、branch coverage 与 Ruff 门已通过；GitHub
Actions 的 Ubuntu Python 3.10/3.12 与 Windows Python 3.12 完整矩阵也已在
2026-08-01 对提交 `6e05edf` 全部通过。Phase 1 Definition of Done 已满足，状态
正式记为 `Completed`。

---

## 6. Phase 2 — Offline Data and Feature Stores

### 目标

建立真实在线 Agent 所依赖的离线数据契约和可版本化 Store。

### 工作内容

- 用户行为序列预处理
- Item Feature schema 和 Store
- Segment Metadata schema 和 Store
- 可替换 Video Segmenter interface
- Fixed-window segmentation baseline
- Cheap Segment Proxy pipeline
- 特征和数据 provenance
- 小规模 fixture dataset

### 交付物

- 可重复生成的 processed data
- 可按 item 查询的 Segment Store
- 可排除已观察片段的查询接口
- feature manifest 和版本信息

### 验收标准

- Online loop 不执行视频切分或批量特征提取
- 同一 preprocessing config 产生可追踪的数据版本
- Segment ID 在 preprocessing、perception、evidence 和 trace 中保持一致

### 本阶段保留为可替换策略

- 最终 segmentation strategy
- 最终 proxy feature set
- ASR/audio 是否进入 Phase 2 第一条 baseline
- 最终 embedding model

---

## 7. Phase 3 — Real Cheap Path: User Memory + SASRec

### 目标

用真实 Cheap Path 替换 Phase 1 中的用户状态和初始排序 Mock。

### User Memory 工作内容

- Preference Atom builder interface
- Long × Short similarity matrix
- stable / emerging / fading baseline
- configurable threshold、EMA、persistence 和 decay
- memory persistence and reload
- drift metrics

### SASRec 工作内容

- sequence dataset
- train/validation/test split
- configurable negative sampling
- model training and checkpointing
- candidate scoring API
- inference adapter

### 集成原则

User Memory 与 SASRec 仍然独立，在 Recommendation State 层汇合。

### 验收标准

- 可单独评估和替换 User Memory
- 可单独训练和调用 SASRec
- Agent Controller 无需修改即可从 Mock 切换到真实 Cheap Path
- 初始 ranking 可在 perception budget 为零时独立运行和评估

---

## 8. Phase 4 — MLLM Evidence and Score-Update Baseline

### 目标

接入真实昂贵感知路径，并建立从 Evidence 到 ranking update 的可解释 baseline。

### 工作内容

- MLLM Perceiver adapter
- frame/clip input resolver
- Information-Need-aware prompt
- raw response logging
- Evidence Parser、schema validation 和 repair
- Evidence State aggregation
- perception cost logging
- Mock Score Updater 的一致性基线
- Residual Score Updater baseline

### 必须记录的成本

- perceived segment count
- segment duration
- processed frames
- input/output tokens
- latency
- model name and version

### 验收标准

- 只有被选择的 segment 触发昂贵感知
- MLLM 输出先变成 Evidence，不直接成为最终 recommendation score
- parser failure 有明确状态，不会静默污染 ranking
- 未观察 item 的 initial prior 仍然有效
- 同一 Evidence 可以离线重放 score update

### 本阶段保留为可替换策略

- 最终 MLLM
- frame sampling
- attribute vocabulary
- evidence embedding
- residual vs unified reranker

---

## 9. Phase 5 — Oracle Data and Supervised Segment Value Model

### 目标

从真实或 Teacher Evidence 构建 expected-gain 数据，训练推荐决策感知的
Segment Value Model。

### 工作内容

- sampled Recommendation State builder
- candidate segment enumeration
- Oracle/Teacher perception pipeline
- before/after ranking simulation
- pluggable recommendation-gain label
- value-model dataset and split
- simple MLP baseline
- regression / pairwise loss adapters
- offline value-model evaluation

### 主要指标

- predicted gain 与 actual gain 的相关性
- pairwise selection accuracy
- top-1 oracle-hit rate
- regret vs oracle
- 同预算下的 end-to-end recommendation gain

### 验收标准

- Label 可以追溯到 state、segment、evidence 和 score-updater version
- Value Model 只读取 online 可用的 cheap features
- Agent Controller 无需修改即可从 Mock Value 切换到 supervised model
- 能与 relevance-only 和 random selection 做同预算比较

### 本阶段保留为可替换策略

- 最终 expected-gain label
- model architecture
- loss
- negative sampling
- value uncertainty

---

## 10. Phase 6 — End-to-End Evaluation and Experiments

### 目标

形成可用于研究结论的完整训练、推理、成本和评估流水线。

### 工作内容

- recommendation metrics
- perception efficiency metrics
- budget curves
- segment-selection baselines
- Agent ablations
- memory evaluation
- value-model evaluation
- experiment config snapshots
- multi-seed aggregation
- case-study trace visualization data

### 必备对比

- No perception
- Random segment
- Uniform segment
- Query-segment similarity
- Top-item-first
- Uncertainty-only
- Proposed Segment Value Model
- Oracle selection
- Full-video perception where feasible

### 验收标准

- 相同预算下可以公平比较所有 selection policies
- 每个结果可追溯到 config、seed、dataset、features 和 checkpoints
- 可以生成 ranking quality vs perception budget 曲线
- 可以分解 recommendation gain、MLLM cost 和 latency

---

## 11. Phase 7 — Optional Advanced Research

只有前述 supervised system 稳定后才进入本阶段。

可能方向：

- Learned Information Need
- richer or learned ranking uncertainty
- Unified Evidence Reranker
- learned stopping
- joint segment-selection and stop action
- value uncertainty and risk-aware selection
- contextual bandit
- reinforcement learning

进入任何一个方向前，需要先定义它相对 Phase 6 baseline 的新增研究问题和
独立验收指标。

---

## 12. 跨阶段不变量

无论使用什么具体实现，以下约束都应持续成立：

1. Candidate selection 在 item 和 segment 两个维度上联合进行。
2. Information Need 在 segment selection 前不绑定具体 item。
3. Expensive perception 只作用于已选择 segment。
4. MLLM 产生 Evidence，不默认直接完成最终排序。
5. Initial ranking prior 在整个 Agent loop 中有明确保留方式。
6. Recommendation State 是每一步完整、可记录的状态快照。
7. 所有停止行为都有结构化 reason。
8. 所有实验都记录感知成本，而不只记录 recommendation accuracy。
9. 所有 `TBD` 研究选择通过接口或配置保留替换能力。
10. Mock、Baseline 和 Learned implementations 可以在同一 Controller 下切换。
