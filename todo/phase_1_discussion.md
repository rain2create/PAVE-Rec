# Phase 1 Discussion Checklist
# Phase 1 逐项讨论清单

## 1. Phase 1 的定位

Phase 1 的目标是构建一个 deterministic Mock Agent Loop，用于验证：

- 模块契约
- State 的语义和流转
- Controller 编排顺序
- budget 与 stop mechanics
- trace 与 replay
- 可复现性
- 端到端工程闭环

Phase 1 不解决任何真实模型的效果问题。

### 已确认边界

Status: `Confirmed`

- User Memory 使用 `MockUserMemory`，不实现动态记忆算法。
- Initial Ranking 使用 `MockInitialRanker`，不训练 SASRec。
- Information Need 使用 `MockInformationNeedEstimator`，不确定真实公式。
- Segment Value 使用 `MockSegmentValueModel`，不确定 label、loss 或架构。
- Perception 使用 `MockPerceiver`，不调用真实 MLLM。
- Score Update 使用 `MockScoreUpdater`，不选择 residual 或 unified reranker。
- Phase 1 的真实实现只覆盖领域契约、状态流转、Controller、Stop control
  flow、trace、配置组装和测试。

### 明确不在本阶段讨论

- Preference Atom extraction / clustering
- Long × Short matching policy
- stable / emerging / fading 算法
- persistence、promotion、decay
- SASRec training details
- 最终 ranking uncertainty 算法
- Information Need vocabulary 或公式
- expected recommendation gain label
- Segment Value architecture 和 loss
- MLLM、frame sampling、ASR 和 prompt 方案
- Evidence embedding 和最终聚合算法
- Residual vs Unified Score Update
- 最终 video segmentation strategy
- RL

---

## 2. 讨论方式

下面的 Decision Gates 按顺序逐个讨论。

每个 Gate 的流程：

```text
Pending
→ 明确问题与依赖
→ 比较选项和取舍
→ 用户 Confirm 或 Deferred
→ 更新本文件和稳定设计文档
→ 只实现已确认部分
```

除已标记为 `Confirmed` 的 Phase 1 边界外，其余条目都不能因为编码方便而
自动视为已确定。

---

## 3. P1-01 — Recommendation State Contract

Status: `Confirmed`

这是 Phase 1 第一个需要讨论的 Gate。Recommendation State 是所有运行模块
共享的中央契约，必须在定义 Schema 和 Controller 前确认。

### 3.1 State 的角色

需要确认：

- State 是某一步的完整 snapshot，还是持有可变对象的运行容器。
- 每次 perception 后是否重新 build 一个新 State。
- State Builder 是唯一构造入口，还是允许 Controller/组件直接修改。
- State 是否只描述当前时刻，还是同时保存 initial/before 信息。

### 3.2 Candidate State

需要确认：

- 是否同时保留 `initial_score` 和 `current_score`。
- 是否同时保留 `initial_rank` 和 `current_rank`。
- ranking 是 State 中的显式字段，还是由 score 计算得到。
- 分数相同时如何保证 deterministic tie-breaking。
- State 保存全部 candidates，还是只保存 top-k candidates。
- candidate cheap features 是完整嵌入、部分摘要，还是通过 Store 引用。

### 3.3 User Memory 在 State 中的表达

需要确认：

- State 保存完整 `UserMemoryState`，还是只保存本步所需的 snapshot/view。
- long-term 和 short-term atoms 是否都直接可见。
- semantic profile 是否属于 Phase 1 schema。
- embedding 等非 JSON 数据是否进入核心 State。
- State 中是否记录 User Memory version 或更新时间。

这里仅讨论表达契约，不讨论真实 Memory 如何产生。

### 3.4 Evidence 与 Segment Observation

需要确认：

- State 内嵌完整 Evidence，还是保存独立 `EvidenceState` snapshot。
- `observed_segment_ids` 的唯一事实来源是什么。
- segment 被标记 observed 的时机。
- failed perception 是否算 observed。
- unobserved segment 列表显式存储，还是根据 Segment Store 和 Evidence 计算。
- Segment Proxy 是否进入 State，还是仅在 Value Model Input 中加载。

### 3.5 Budget 与 Step

需要确认：

- Phase 1 的 `remaining_budget` 是否只表示剩余 perception action 次数。
- 是否现在就定义可扩展的 `BudgetState`，为 token/frame/latency cost 留接口。
- step 从 0 还是 1 开始。
- step 表示 decision iteration，还是 successful perception count。
- failed perception 是否增加 step、扣减 budget。

### 3.6 Ranking Uncertainty

需要确认：

- Phase 1 State 只保留通用 uncertainty 字段，还是提供一个 V1 margin baseline。
- uncertainty 保存原始 signals，还是保存最终聚合值。
- uncertainty 缺失时 Stop Policy 和 Information Need Mock 如何处理。

本 Gate 不确定最终 uncertainty 算法。

### 3.7 Metadata、版本和序列化

需要确认：

- State 必须记录哪些 dataset、feature 和 component versions。
- metadata 是否允许自由扩展，还是定义稳定字段。
- State 是否要求完全 JSON serializable。
- Tensor/array 类型如何进入日志：排除、转 list、保存引用或单独落盘。
- 是否为 State schema 增加显式 version。

### P1-01 的交付结果

完成本 Gate 后应得到：

- 确认后的 `RecommendationState` 语义
- 确认后的 `CandidateState` 字段
- State Builder 的输入输出边界
- State mutation/rebuild 规则
- serialization 规则
- 各组件可以读取的 State 范围

### P1-01 Decision Record

```text
Decision ID: P1-01
Status: Confirmed
Decision:
1. RecommendationState 是某一决策时刻的只读完整快照，只能由
   RecommendationStateBuilder 构造。组件不能原地修改 State；每次
   perception action 后基于独立的运行时 scores、Evidence/Observation
   State 和 action counters 重新构造。
2. CandidateState 保存全部 candidates，并同时保存 initial_score、
   current_score、initial_rank 和 current_rank。相同 score 使用稳定的
   item_id 次序打破并列。
3. Candidate cheap features、segment proxy features 和所有 Tensor/array
   只通过带版本的 reference 暴露，不直接进入 State。
4. State 内嵌紧凑、只读、可序列化的 UserMemoryView。它包含 long-term
   和 short-term atom 摘要、stable/emerging/fading match signals、drift、
   memory version/update time 和可选 semantic profile；embedding 和原始
   Long x Short Similarity Matrix 只保存 reference。Information Need 消费
   Matrix 的派生决策信号，未来 learned implementation 可以按 reference
   加载完整 Matrix。
5. Segment Observation 与成功 Evidence 分开表达。每个 segment 在 Phase 1
   使用 unobserved、succeeded、failed 三种状态；failed action 不自动重试。
   运行时 Evidence/Observation State 是唯一事实来源，CandidateState 中的
   observation 和 unobserved 列表都是构造时生成的快照。
6. Phase 1 不建立多维 Budget 系统，只配置 max_perception_actions。
   remaining_perception_actions 表示剩余可发起的 perception action 数量。
   step 从 0 开始，表示本次 run 已发起的 perception action 数量；只有调用
   Perceiver 才增加 step，失败调用同样增加 step 并消耗一次 action。
7. Phase 1 的 ranking uncertainty 只保存原始 top1_top2_margin signal。
   Stop threshold 配置化；更丰富或 learned uncertainty 延后。
8. RecommendationState 必须完全 JSON serializable，并包含显式
   schema_version 和 run_id。核心字段不能藏在自由 metadata 中；dataset、
   feature、component 和 code versions 记录在 run manifest、trace 或带版本
   reference 中。
Rationale:
保持 Agent loop 的状态一致性、确定性、可回放性和模型/存储解耦，同时避免
将 Phase 1 扩展成真实算法、长上下文或多维成本系统。
Alternatives considered:
可变 State、top-k-only State、内嵌 Tensor、通过 Evidence 推断 observed、
失败自动重试、完整 BudgetState、将原始 Similarity Matrix 直接放入 State。
Affected schemas/interfaces:
RecommendationState, CandidateState, UserMemoryView, PreferenceAtomView,
PreferenceMatchView, EvidenceState, SegmentObservationState,
RecommendationStateBuilder.
Affected docs/tests:
docs/01_dynamic_hybrid_user_memory.md, docs/03_recommendation_state.md,
docs/07_evidence_score_update.md; P1-02 schemas and P1-09 tests.
Deferred follow-up:
P1-03 确认组件最小输入和 Observation ownership；P1-05 确认完整状态机；
P1-06 确认 stop reason priority；P1-07 确认 trace/replay layout；Phase 4
讨论真实 MLLM retry/repair、prompt context 和 token/frame/latency cost。
Confirmed by: User
Date: 2026-07-30
```

---

## 4. P1-02 — Shared Domain Schemas

Status: `Confirmed`

在 Recommendation State 确认后，讨论其他公共领域对象。

### 需要确认

- 每个 schema 的最小必要字段。
- `item_id`、`segment_id`、`user_id` 是否统一为 `str`。
- 时间使用 interaction index、Unix timestamp 还是两者兼容。
- schema 使用标准 dataclass、validated model 或其他表示。
- 哪些对象允许修改，哪些对象应当 immutable。
- Optional 字段的默认语义。
- score、confidence、strength、value 的取值范围是否在 schema 校验。
- embedding/Tensor 是否属于领域对象，或只属于模型实现层。
- schema versioning 和向后兼容要求。
- Evidence、Trace 和 Run Result 的 JSON serialization 规则。

### 本 Gate 涉及的对象

- `PreferenceAtom`
- `UserMemoryState`
- `InitialRankingOutput`
- `SegmentMeta`
- `SegmentProxy`
- `CandidateState`
- `RecommendationState`
- `InformationNeed`
- `Evidence`
- `ItemEvidenceState`
- `EvidenceState`
- `SegmentValueInput`
- `SegmentValue`
- `StopDecision`
- `AgentStepTrace`
- `AgentRunResult`

### P1-02 的交付结果

- schema 清单和字段定义
- schema 之间的 ownership 关系
- validation 与 serialization 约定
- Phase 1 所需的最小 domain implementation

### P1-02 Decision Record

```text
Decision ID: P1-02
Status: Confirmed
Decision:
1. 公共 domain schema 使用 strict、frozen Pydantic models，并禁止未声明字段。
2. 所有 user/item/segment/atom/evidence/need/run ID 使用非空 str。
3. 公共 domain objects 不可变；Updater 返回新对象，内部实现可以使用局部可变
   数据结构。
4. 事件时间使用 Unix epoch milliseconds，字段显式命名为 *_at_ms；行为顺序
   可以另外使用非负 interaction_index。
5. strength、persistence、confidence 使用 [0, 1]；cosine similarity 使用
   [-1, 1]；rank 从 1 开始；step/action counters 非负；score 和 segment value
   只要求为 finite float，不假设是概率，value 可以为负。
6. None 表示未提供、不可用或尚未计算；空 collection 表示已经计算但结果为空。
7. domain 中不允许 Tensor、ndarray、model、tokenizer、Store、file handle 或
   arbitrary Python object。所有大型/模型相关数据使用 ResourceRef；加载后的
   tensor batch 属于具体模型实现。
8. 固定状态使用 Enum。PreferenceState 和 ObservationStatus 在 P1-02 定义；
   StopReason 的值在 P1-06 确认。
9. 独立持久化的顶层 RecommendationState、AgentStepTrace 和 AgentRunResult
   带 schema_version。metadata 只能保存非核心 JSON-compatible 扩展字段。
10. 共享 schema 按 refs、memory、ranking、segments、evidence、state、
    decisions、trace 和 serialization 分模块维护；domain/__init__.py 只导出
    稳定公共类型。
Schema inventory:
ResourceRef; PreferenceAtomView; PreferenceMatchView; UserMemoryView;
InitialRankedCandidate; InitialRankingOutput; SegmentMeta; SegmentProxyRef;
Evidence; SegmentObservationState; ItemEvidenceState; EvidenceState;
CandidateState; RankingUncertainty; RecommendationState; InformationNeed;
CandidateSegmentRef; SegmentValueInput; SegmentValue; StopDecision;
AgentStepTrace; AgentRunResult.
Rationale:
以严格、可序列化、不可变的公共契约支持 deterministic replay，并防止模型实现、
Tensor 或任意 metadata 污染 Agent harness。
Alternatives considered:
标准库 dataclass、可变 domain objects、integer-only IDs、模糊 int/float 时间、
内嵌 Tensor、scores dict + ranking list、任意字符串状态和宽松 extra fields。
Affected docs/tests:
docs/00_shared_domain_schemas.md；各模块文档中的 schema 示例；P1-09 schema
validation/serialization tests。
Deferred follow-up:
P1-03 确认接口参数和 ownership；P1-06 确认 StopReason；P1-07 补全
AgentStepTrace、AgentRunResult 和持久化布局。
Confirmed by: User
Date: 2026-07-30
```

---

## 5. P1-03 — Component Interfaces and Ownership

Status: `Pending`

本 Gate 只讨论组件怎样协作，不讨论真实算法内部怎样计算。

### 需要确认

- 每个接口的准确输入和输出。
- 接口接收完整 State，还是最小必要参数。
- 返回新对象，还是允许原地更新传入对象。
- Store 返回 copy、view 还是不可变对象。
- V1 接口是 synchronous 还是需要为 async perception 预留 adapter。
- batch API 是否现在需要，还是延后。
- 空 candidate、空 segment、缺失 feature 的统一行为。
- 可恢复错误与不可恢复错误的分类。
- 组件异常由组件转换还是由 Controller 处理。
- 组件名称和版本如何写入 trace。

### 需要定义的接口

- `UserMemory`
- `InitialRanker`
- `ItemFeatureStore`
- `SegmentStore`
- `RecommendationStateBuilder`
- `InformationNeedEstimator`
- `SegmentValueModel`
- `SegmentPerceiver`
- `EvidenceUpdater`
- `ScoreUpdater`
- `StopPolicy`
- `TraceWriter`

### P1-03 的交付结果

- 确认后的接口签名
- mutation 和 ownership 约定
- error contract
- Mock 与未来真实实现必须共同满足的行为约束

---

## 6. P1-04 — Deterministic Mock Scenario

Status: `Pending`

Mock 场景必须足以验证 Agent 行为，但不能暗中成为真实算法 baseline。

### 需要确认

- fixture 使用多少用户、candidates 和 segments。
- 是否设计一个固定用户同时包含 stable、emerging 和 fading atoms。
- 初始 ranking 是否需要 top1/top2 接近。
- 是否必须让 rank-2 item 的某个 segment 首先被选择。
- Mock Evidence 如何触发一次可观察的 score change。
- 完整场景运行几个 perception steps。
- 需要覆盖哪些 stop reason。
- Mock 是否完全查表，还是允许 seed-controlled pseudo-random behavior。
- fixture 和 expected trace 是否作为 golden test versioned。

### Mock 必须证明的行为

- Information Need 可以消费 User Memory。
- Segment Value 在所有 `(item, segment)` 间比较。
- 被选择片段产生 Evidence。
- Evidence 可以改变 score 和 ranking。
- 已观察片段不会再次出现。
- loop 可以因不同原因停止。

### P1-04 的交付结果

- Mock fixture specification
- 每个 Mock component 的确定性映射
- 至少一个完整 expected run
- 不属于真实研究算法的明确声明

---

## 7. P1-05 — Controller State-Transition Order

Status: `Pending`

### 建议讨论的完整顺序

```text
build user memory
→ load candidates and segments
→ initial rank
→ create empty evidence state
→ build recommendation state
→ pre-value stop check
→ estimate information need
→ enumerate unobserved segments
→ predict segment values
→ post-value stop check
→ select segment
→ perceive
→ update evidence
→ update scores
→ update budget and step
→ write trace
→ rebuild state
```

以上是待确认的执行顺序，不因出现在文档中就自动视为最终决定。

### 需要确认

- Information Need 在第一次 stop check 之前还是之后计算。
- 无 unobserved segments 时由 Store、Controller 还是 Stop Policy 处理。
- empty value output 的行为。
- segment value 并列时的选择规则。
- Evidence update 与 observed 标记的先后顺序。
- score update 失败时是否保留 Evidence。
- trace 在每个动作前写、动作后写，还是一次写完整 step。
- budget 和 step 在 perception 前还是成功后更新。
- perception/parse failure 是 retry、skip、stop 还是显式 failed step。
- Controller 是否需要 maximum-loop safety guard。
- Controller 返回 ranking，还是完整 `AgentRunResult`。

### P1-05 的交付结果

- 确认后的状态机
- 正常路径和失败路径
- Controller 的职责边界
- 每种退出路径的结果结构

---

## 8. P1-06 — Budget and Stop Semantics

Status: `Pending`

本 Gate 讨论控制语义，不确定最终 learned stop policy。

### 需要确认

- Phase 1 budget 的基本单位。
- 是否同时记录 action、frame、token、latency 的占位 cost fields。
- budget 为零时是否仍构造并记录 step-0 State。
- perception 调用失败是否消耗 budget。
- Stop Policy 的两个调用位置是否保留。
- stop reasons 使用 enum 还是自由文本。
- 多个条件同时满足时的 reason 优先级。
- ranking certainty stop 在 Phase 1 使用 Mock signal 还是 configurable margin baseline。
- low segment value stop 使用 Mock signal 还是 configurable numeric threshold。
- 是否允许显式 external cancellation。

### 至少需要表达的停止原因

- budget exhausted
- ranking sufficiently certain
- no unobserved segments
- maximum segment value too low
- invalid or empty candidate set
- component failure
- safety limit reached

### P1-06 的交付结果

- Budget contract
- StopDecision contract
- stop reason taxonomy
- 两阶段 stop control flow
- budget/step 更新不变量

---

## 9. P1-07 — Trace, Replay, and Reproducibility

Status: `Pending`

### 需要确认

- 每个 run 的目录命名和 run ID。
- trace 是一个 step 一行 JSONL，还是 event-based JSONL。
- step trace 保存完整 State，还是保存 before/after 摘要。
- 是否保存所有 segment values。
- 是否保存 Mock/MLLM raw output。
- 大型 embeddings 和 features 是内嵌、引用还是排除。
- resolved config 保存格式。
- seed、dataset version、component version 和 Git commit 是否必填。
- final result 与 trace 分开还是合并保存。
- replay 是重放已保存输出，还是重新执行 deterministic components。
- 日志写入失败是否中断 Agent。
- 用户数据和媒体路径需要怎样脱敏。

### 最小 Trace 候选字段

- step
- ranking and scores before
- Recommendation State summary
- Information Need
- candidate segment values
- selected segment
- Evidence
- scores and ranking after
- budget before/after
- stop decision and reason
- component versions
- timing and cost placeholders

### P1-07 的交付结果

- AgentStepTrace schema
- AgentRunResult schema
- JSONL layout
- run-directory layout
- deterministic replay definition

---

## 10. P1-08 — Configuration, Bootstrap, and CLI

Status: `Pending`

CLI 是薄入口；核心 Agent 必须可以被 Python 直接调用。

### 需要确认

- 配置使用单文件、分组文件还是组合式 overrides。
- Phase 1 是否引入第三方 config framework。
- 配置 schema 是否做类型校验。
- component implementation 如何通过配置选择。
- path 是相对 repository、config file 还是 current working directory。
- bootstrap/factory 的职责边界。
- Python API 的最小调用方式。
- CLI 使用 `python -m ...` 还是安装后的 console command。
- 输入 fixture 从配置、文件还是命令参数指定。
- output directory 冲突时覆盖、报错还是生成新 run ID。
- CLI exit code 和错误输出约定。

### 必须保持的边界

```text
CLI
→ load config
→ bootstrap components
→ call AgentController.run(...)
→ save/report result
```

CLI 中不能实现 Information Need、Value selection、Score Update 或 Stop Policy。

### P1-08 的交付结果

- config layout
- typed config contract
- bootstrap responsibility
- Python API example
- CLI invocation and output convention

---

## 11. P1-09 — Test Matrix and Phase Acceptance

Status: `Pending`

### Unit Tests

需要确认并覆盖：

- schema validation and serialization
- deterministic reranking and tie-breaking
- State build/rebuild
- observed/unobserved segment bookkeeping
- budget updates
- stop reason precedence
- evidence append/update behavior
- score-prior preservation invariant

### Integration Tests

- User Memory → Recommendation State
- State → Information Need
- State/Need/Segments → Segment Value
- selected segment → Evidence
- Evidence → Score Update
- Score Update → State rebuild
- Controller → Trace Writer

### End-to-End Tests

- standard multi-step Mock run
- zero-budget run
- no-unobserved-segment run
- ranking-certainty stop
- low-value stop
- failure-path run
- same seed/config deterministic replay

### Phase 1 验收候选标准

- 同一输入、配置和 seed 得到相同结果。
- segment 不会被重复观察。
- 每个 successful perception 恰好按确认规则更新 budget 和 step。
- 未观察 item 保留有意义的 initial ranking prior。
- 每一步都产生符合契约的 Recommendation State。
- 每个退出路径都有结构化 stop reason。
- JSONL trace 足以完成确认定义下的 replay。
- Controller 只依赖接口。
- 所有真实研究算法仍为 Mock、Deferred 或 TBD。

### P1-09 的交付结果

- 最终测试矩阵
- Phase 1 Definition of Done
- 允许进入实现和验收的明确边界

---

## 12. Phase 1 Discussion Order

按以下顺序推进，一次只处理一个 Gate：

1. `P1-01 Recommendation State Contract`
2. `P1-02 Shared Domain Schemas`
3. `P1-03 Component Interfaces and Ownership`
4. `P1-04 Deterministic Mock Scenario`
5. `P1-05 Controller State-Transition Order`
6. `P1-06 Budget and Stop Semantics`
7. `P1-07 Trace, Replay, and Reproducibility`
8. `P1-08 Configuration, Bootstrap, and CLI`
9. `P1-09 Test Matrix and Phase Acceptance`

某个 Gate 可以显式 `Deferred`，但必须记录：

- 为什么现在不决定
- 哪个接口隔离它
- Mock 使用什么测试语义
- 在哪个后续 Phase 重新讨论

---

## 13. Decision Record Template

每次确认后，在对应 Gate 下追加：

```text
Decision ID:
Status: Confirmed | Deferred
Decision:
Rationale:
Alternatives considered:
Affected schemas/interfaces:
Affected docs/tests:
Deferred follow-up:
Confirmed by:
Date:
```

只有 `Confirmed` 的内容可以被当作 Phase 1 实现要求。
