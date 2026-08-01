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

- Phase 1 的 `remaining_perception_actions` 是否只表示剩余 perception action 次数。
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
   feature、component 和 code versions 记录在 resolved config、Trace、Result
   或带版本 reference 中。
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
Resolved follow-up:
P1-03 已确认组件最小输入和独立 ObservationUpdater ownership；P1-05 已确认
完整状态机。
Deferred follow-up:
P1-06 已确认 stop reason priority；P1-07 已确认 trace/replay layout；Phase 4
讨论真实 MLLM retry/repair、prompt context 和 token/frame/latency telemetry。
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

- `ResourceRef`
- `PreferenceState`
- `PreferenceMatchType`
- `ObservationStatus`
- `PreferenceAtomView`
- `PreferenceMatchView`
- `UserMemoryView`
- `InitialRankingOutput`
- `SegmentMeta`
- `SegmentProxyRef`
- `CandidateState`
- `RecommendationState`
- `InformationNeed`
- `Evidence`
- `ItemEvidenceState`
- `EvidenceState`
- `ItemObservationState`
- `ObservationState`
- `SegmentValueInput`
- `SegmentValue`
- `StopDecision`
- `AgentStepTrace`
- `AgentRunResult`

Memory 内部的 `PreferenceAtom`、`UserMemoryState` 和 Tensor 不属于公共 Domain
Schema；P1-02 只确认它们通过 `UserMemoryView`/`ResourceRef` 穿越模块边界。

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
1. 公共 domain schema 使用 Pydantic v2 strict、frozen models，并禁止未声明
   字段。Frozen 保证顶层字段不可重新赋值；嵌套 JSON payload 在 validation
   时复制并按只读契约使用，任何更新都构造新对象。
2. 所有 user/item/segment/atom/evidence/need/run ID 使用非空 str。
3. 公共 domain objects 不可变；Updater 返回新对象，内部实现可以使用局部可变
   数据结构。
4. 事件时间使用 Unix epoch milliseconds，字段显式命名为 *_at_ms；行为顺序
   可以另外使用非负 interaction_index。
5. strength、persistence、confidence 使用 [0, 1]；cosine similarity 使用
   [-1, 1]；rank 从 1 开始；step/action counters 非负；score 和 segment value
   只要求为 finite float，不假设是概率，value 可以为负。
6. None 表示未提供、不可用或尚未计算；`T | None` 默认并显式序列化为 null。
   空 collection 表示已经计算但结果为空，语义 collection 不用默认空值掩盖
   “尚未计算”。
7. domain 中不允许 Tensor、ndarray、model、tokenizer、Store、file handle 或
   arbitrary Python object。所有大型/模型相关数据使用 ResourceRef；加载后的
   tensor batch 属于具体模型实现。
8. 固定状态使用 Enum。PreferenceState、PreferenceMatchType 和
   ObservationStatus 在 P1-02 定义；StopReason 的值由 P1-06 补充确认。
9. 独立持久化的顶层 RecommendationState、AgentStepTrace 和 AgentRunResult
   带 schema_version。metadata 只能保存非核心 JSON-compatible 扩展字段。
10. Evidence 与 Observation 使用独立 runtime state。EvidenceState 只保存有效
    Evidence；ObservationState 是 attempt/status 的唯一事实来源；CandidateState
    中对应字段是 Builder 生成的只读派生快照。
11. 共享 schema 按 refs、memory、ranking、segments、evidence、state、
    decisions、trace 和 serialization 分模块维护；domain/__init__.py 只导出
    稳定公共类型。
12. Schema validators 必须检查 ID uniqueness、ranking continuity、reference
    identity、Evidence/Observation consistency 和 budget equation 等跨字段
    invariants。Segment 使用 `(item_id, segment_id)` 复合 identity；segment_id
    只在所属 item 内唯一，不要求跨 items 全局唯一。
Schema inventory:
PreferenceState; PreferenceMatchType; ObservationStatus;
ResourceRef; PreferenceAtomView; PreferenceMatchView; UserMemoryView;
InitialRankedCandidate; InitialRankingOutput; SegmentMeta; SegmentProxyRef;
Evidence; SegmentObservationState; ItemEvidenceState; EvidenceState;
ItemObservationState; ObservationState;
CandidateState; RankingUncertainty; RecommendationState; InformationNeed;
CandidateSegmentRef; SegmentValueInput; SegmentValue; StopReason; StopDecision;
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
Resolved follow-up:
P1-03 已确认接口参数、最小可见范围和 updater ownership。
Deferred follow-up:
P1-06 已补全 StopReason；P1-07 已补全 AgentStepTrace、AgentRunResult 和
持久化布局。
Confirmed by: User
Date: 2026-07-30

Consistency review:
2026-07-31 对 P1-02 做跨文档复核，补充 Pydantic frozen 的浅层不可变边界、
PreferenceMatchType、独立 ObservationState 和跨对象 validators。这些修正只消除
Schema 歧义，不改变 User Memory、Ranking、Perception 或 Score Update 的业务
流程与研究选择。
```

### P1-02 Review Conclusion

Status: `Confirmed with consistency corrections`

复核结论：P1-02 的总体设计适合 Phase 1，可以继续作为公共 Domain Contract。
以下选择保持有效：

- Pydantic v2 strict/frozen 顶层模型
- 非空 string IDs 和明确的 millisecond timestamps
- finite/range validation
- `None` 与空 collection 的不同语义
- Tensor/模型资源通过 `ResourceRef` 隔离
- Enum、schema version 和禁止 extra fields

本次只补强四个工程一致性问题：

1. 明确 frozen 是浅层保护，嵌套 JSON payload 必须 copy-on-validation 并按只读
   契约使用。
2. 将 Evidence 与 Observation runtime state 分开，避免两个事实来源。
3. 使用独立 `PreferenceMatchType`，避免 atom state 与 match classification
   混用。
4. 增加 ID、ranking、reference、observation 和 budget 的跨对象 validators。

P1-03 已完成组件签名和 ownership；P1-06 已完成 StopReason 和 stop priority；
P1-07 已完成 AgentStepTrace/AgentRunResult。

---

## 5. P1-03 — Component Interfaces and Ownership

Status: `Confirmed`

本 Gate 只讨论组件怎样协作，不讨论真实算法内部怎样计算。

### 需要确认

- 每个接口的准确输入和输出。
- 接口接收完整 State，还是最小必要参数。
- 公共 domain object 已确认不能原地修改；需要确认由哪个组件构造并返回新对象。
- Observation transition 由 Controller、独立 Updater 还是其他组件负责。
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
- Observation transition owner / optional `ObservationUpdater`
- `ScoreUpdater`
- `StopPolicy`
- `TraceWriter`

### P1-03 的交付结果

- 确认后的接口签名
- mutation 和 ownership 约定
- error contract
- Mock 与未来真实实现必须共同满足的行为约束

### P1-03 Decision Record

```text
Decision ID: P1-03
Status: Confirmed
Decision:
1. Phase 1 component interfaces 使用 synchronous typing.Protocol，不要求继承
   共同业务父类；async/concurrent MLLM 留到 Phase 4。
2. 默认最小输入权限。Information Need 和 Stop Policy 可以消费全局决策状态；
   Perceiver、Updater、Stores 等只获得职责所需输入，不能读取 Controller globals。
3. 简单操作使用显式参数；复杂操作使用 strict/frozen interface DTO。新增：
   ComponentDescriptor, CandidateScore, ItemFeatureRef, ItemSegmentCatalog,
   RecommendationStateBuildRequest, PerceptionRequest, PerceptionResult,
   ScoreUpdateRequest。
4. Evidence 与 Observation 分别由 pure EvidenceUpdater 和 ObservationUpdater
   返回新状态。Perceiver 只返回 PerceptionResult，不管理 Agent runtime state；
   Controller 只编排已确认的转换顺序。
5. 可预期 perception failure 使用 typed failed PerceptionResult，不创建空/伪
   Evidence。契约错误、资源解析错误和不可恢复执行错误分别使用 ContractError、
   ResourceResolutionError 和 ComponentExecutionError。
6. InitialRanker、Stores 和 SegmentValue 使用天然 batch；SegmentPerceiver
   一次只观察一个已选 segment。Segment Value output 必须与 input segments
   一一覆盖；不得 duplicate、missing 或 extra。
7. Store 只发布静态 metadata/references，不执行 Observation filtering 或策略。
   每个请求 item 必须有显式返回 entry，不能静默遗漏。
8. 每个 component 暴露只读 ComponentDescriptor(role, implementation, version)；
   config 中的短 implementation selector 与 descriptor 中的稳定 runtime
   implementation ID 是两个显式概念。P1-07 已确认 descriptors 只在
   AgentRunResult 保存一次，P1-08 已确认由 Bootstrap 按固定 config role 顺序
   收集并在构造 Controller 时注入。
9. StopPolicy 的 pre/post-value 方法、StopReason 和 priority 已由 P1-06
   确认；TraceWriter 的完整方法和失败语义已由 P1-07 确认。
Complexity guardrails:
Phase 1 不引入 async controller、DI framework、plugin registry、generic repository、
event bus、通用 Result[T, E] 或多层 BaseComponent。
Rationale:
用最少接口隔离 Mock 与未来真实实现，同时防止组件获得不必要的全局状态、隐藏
mutation 或把正常 perception failure 伪装成异常/空 Evidence。
Alternatives considered:
ABC inheritance、所有组件接收完整 RecommendationState、Controller 直接修改
Observation、Perceiver 返回更新后 State、exception-only failure、全接口 async、
逐 segment Value 调用、Store 执行 runtime policy filtering。
Affected docs:
docs/00_component_interfaces.md；docs/02—09 的接口示例；P1-04 Mock contracts；
P1-05 Controller state machine；P1-09 interface/integration tests。
Resolved follow-up:
P1-05 已确认 attempt_step、异常后的 run 行为和完整调用顺序；P1-06 已确认
StopPolicy 的签名、taxonomy 和 priority；P1-07 已确认 TraceWriter；P1-08 已确认
Bootstrap 通过稳定 ID 和显式 constructor mapping 实例化 Protocol implementations。
Deferred follow-up:
Phase 4 重新评估 async MLLM adapter。
Confirmed by: User
Date: 2026-07-31
```

---

## 6. P1-04 — Deterministic Mock Scenario

Status: `Confirmed`

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

权威 Mock specification 见
[`../docs/00_deterministic_mock_scenario.md`](../docs/00_deterministic_mock_scenario.md)。

### P1-04 Decision Record

```text
Decision ID: P1-04
Status: Confirmed
Decision:
1. Canonical mock-v1 使用一个主用户、三个 candidates，每个 candidate 两个
   segments；candidate 顺序固定为 item_a、item_b、item_c。
2. Mock User Memory 同时包含 stable plot-twist、emerging AI-visuals 和
   fading slow-drama signals。Information Need 通过固定 memory signature
   查表并引用 plot-twist atoms，只验证 Memory 消费路径，不实现 NTD 或真实
   need estimation。
3. Initial scores 为 A=0.81、B=0.79、C=0.61。第一个被选择的 segment 必须是
   rank-2 的 B.segment_1，其 value=0.90，是全部六个 segment 中的最大值。
4. B.segment_1 产生 evidence_b_1，并将 B 的 Mock score 更新为 0.87，使
   ranking 从 A>B>C 变为 B>A>C。
5. Canonical run 执行两次 perception。第二步不得再次枚举 B.segment_1，
   选择 A.segment_2；最终 scores 为 B=0.87、A=0.78、C=0.61，budget 归零。
6. 所有 Mock component 使用 versioned fixture 完全查表。canonical run 记录
   seed=7，但不依赖 pseudo-random behavior。
7. 主场景预期走 budget-exhausted 退出路径；zero-budget、high-certainty、
   no-segments、low-values、perception-failed 和 component-exception 使用
   最小 fixture overrides。P1-05 已确认正常 failure continuation 和 exception
   termination；P1-06 已确认 stop taxonomy 和 priority。
8. Fixture 和 semantic expected run 以 mock-v1 纳入版本控制。精确 JSONL
   golden trace 按 P1-07 已确认的 Trace Schema 在 P1-09 实现。
9. Mock score delta、Evidence attributes 和 Value numbers 都只是测试映射，
   不构成 User Memory、Information Need、Segment Value、Evidence
   aggregation 或 Score Update 的真实 baseline。
Rationale:
用最小的两步场景同时证明跨 item 全局选段、rank-2 优先感知、Evidence 驱动
换位、已观察 segment 排除、累计状态重建、未观察 item prior 保留和 budget
扣减；完全查表保证 expected run 稳定且不会暗中固化研究算法。
Alternatives considered:
单 candidate/两个 candidates、每个 item 一个 segment、只运行一次 action、
首先观察 rank-1、随机生成 scores/evidence、在 P1-07 前锁定 JSONL golden
format。
Affected docs:
docs/00_deterministic_mock_scenario.md；Phase 1 Mock implementations；
P1-05 Controller state machine；P1-06 Stop Policy；P1-07 golden trace；
P1-09 integration/E2E tests。
Resolved follow-up:
P1-05 已确认 exact state-transition order 和失败后的 run 行为；P1-06 已确认
StopReason/priority/threshold semantics；P1-07 已确认 trace fields，实现在
P1-09 固化 golden JSONL assertions；P1-08 已确认 fixture/config bootstrap。
Confirmed by: User
Date: 2026-07-31
```

---

## 7. P1-05 — Controller State-Transition Order

Status: `Confirmed`

### 已确认的完整顺序

```text
validate run input
→ one-time User Memory / Stores / Initial Ranking initialization
→ create empty Evidence and Observation States
→ build step-0 Recommendation State
→ enter budget-derived safety guard
→ pre-value stop check
→ estimate Information Need
→ project all unobserved segments
→ batch Segment Value prediction
→ deterministic best-value lookup
→ post-value stop check
→ perceive selected segment
→ stage Observation/Evidence transition
→ update scores on success
→ update budget and step
→ rebuild Recommendation State
→ emit completed transition
→ next iteration
```

Declared exception 和 partial-progress 路径以 Decision Record 和
`docs/08_agent_controller.md` 为准。

### 已解决的讨论问题

本 Gate 讨论并解决了：

- Information Need 与 pre-value stop 的先后顺序。
- no-unobserved、empty value 和 output coverage 的处理。
- Segment Value tie-break。
- Evidence、Observation、score 和 counters 的发布边界。
- ScoreUpdater 失败时 Evidence 是否保留。
- completed transition 和 terminal trace 的逻辑时机。
- 正常 failed result 与 declared exception 的不同控制流。
- budget-derived maximum-loop safety guard。
- Controller 的完整 `AgentRunResult` 返回边界。

### P1-05 的交付结果

- 确认后的状态机
- 正常路径和失败路径
- Controller 的职责边界
- 每种退出路径的结果结构

权威 Controller state machine 见
[`../docs/08_agent_controller.md`](../docs/08_agent_controller.md)。

### P1-05 Decision Record

```text
Decision ID: P1-05
Status: Confirmed
Decision:
1. 先验证 run input；空或重复 candidate ID 是启动前 ContractError。User
   Memory、static Stores、Initial Ranker、empty Evidence/Observation 初始化和
   step-0 State build 只在 loop 外执行一次。
2. 每轮首先执行 pre-value stop；只有 continue 时才估计 Information Need、
   projection unobserved segments 并批量调用 Segment Value Model。Value 后、
   Perceiver 前执行 post-value stop。
3. remaining action 为 0 或没有 unobserved segment 时，pre-value StopPolicy
   必须停止。若 policy 错误地 continue，Controller 抛出 ContractError，不允许
   超预算 action，也不对空 segments 调用 Value Model。非空 input 对应
   empty/missing/extra Value output 同样是 ContractError。
4. Segment Value 并列时按 (item_id, segment_id) 升序打破并列。
5. 正常 success result 先产生 staged Observation/Evidence transition，只在合法
   update 后发布新 State；ScoreUpdater 只在 success 时调用。
6. 正常 failed result 标记 segment failed，不创建 Evidence、不改变 scores，
   但增加 step、扣减 action、重建 State；不重试该 segment，仍有可行动作时
   继续 loop。
7. attempt_step = current State.step + 1，并等于本次正常 result 完成后新 State
   的 step；remaining = max_perception_actions - step。
8. ScoreUpdater 失败时保留已成功取得并验证的 Evidence、Observation 和本次
   action counter，scores 保留上一版，随后以 component failure 终止。
   EvidenceUpdater/ObservationUpdater 失败时不发布不一致 post-State，保留最后
   一个合法 State，并在 terminal result/trace 中记录 attempt/error。
9. ContractError、ResourceResolutionError 和 ComponentExecutionError 都终止
   当前 run，不自动继续或伪造空输出；未声明的编程异常向外传播。业务/运行时
   declared exception 在 TraceWriter 健康时写 terminal trace/result；TraceWriter
   自身 failure 使用 P1-09 的 artifact-sink 特殊边界并向调用方传播。
10. 正常 action 在 post-State rebuild 后提交 completed transition；pre/post
    stop 提交 terminal outcome；业务/运行时 declared exception 在 Writer 健康时
    提交 terminal failure。JSONL/event 字段和写入失败语义留给 P1-07/P1-09。
11. Controller 最多允许 max_perception_actions + 1 次 decision-loop 进入，并
    在 terminal trace/result 成功持久化后返回完整 AgentRunResult，而不是只返回
    ranking。TraceWriter failure 不返回未完整持久化的 Result。Result 字段留给
    P1-07。
Rationale:
先排除无需行动的状态，再计算 Need/Value；每个正常 Perceiver result 对应一次
清晰、可重建的 counter/state transition。正常 perception failure 可以继续，
结构/资源/组件异常则终止，避免隐藏错误或发布跨对象不一致 State。Controller
只保留 orchestration、确定性 projection/tie-break 和安全控制，不承载研究逻辑。
Alternatives considered:
每轮重新构建 Memory/initial ranking；Information Need 在 pre-stop 前计算；
Store 过滤 observed segments；Value Model 返回空时静默停止；并列随机选择；
failed perception 直接终止或自动重试；异常转换为空 Evidence；Controller 只返回
ranking；无 hard safety guard。
Affected docs:
docs/08_agent_controller.md；docs/00_component_interfaces.md；
docs/07_evidence_score_update.md；docs/00_deterministic_mock_scenario.md；
P1-06 Stop contract；P1-07 Trace/Result；P1-09 state-machine tests。
Resolved follow-up:
P1-06 已确认 StopPolicy 精确签名、StopReason、priority、threshold 和异常
action 的 budget accounting；P1-07 已确认 AgentStepTrace/AgentRunResult、
terminal attempt 和 writer failure semantics；P1-08 已确认 AgentRunRequest 和
run input/bootstrap。
Confirmed by: User
Date: 2026-07-31
```

---

## 8. P1-06 — Budget and Stop Semantics

Status: `Confirmed`

本 Gate 讨论控制语义，不确定最终 learned stop policy。

### 已确认范围

- Phase 1 budget 只表示 perception action 次数。
- 不增加多维 BudgetState、PerceptionCost 或 frame/token/latency 占位 schema。
- budget 为零仍构造 step-0 State。
- succeeded、failed 和 Perceiver declared exception 的 action accounting 明确。
- Stop Policy 使用 pre-value/post-value 两个显式方法。
- stop reasons 使用 enum 和确定性 priority。
- ranking certainty 使用 configurable margin threshold。
- low segment value 使用 configurable numeric threshold。
- Phase 1 不支持结构化 external cancellation。

### Stop reasons

- budget exhausted
- ranking sufficiently certain
- no unobserved segments
- maximum segment value too low
- component failure
- safety limit reached

空或重复 candidate input 已由 P1-05 确认为 run 启动前 `ContractError`，不进入
正常 StopReason taxonomy。

### P1-06 的交付结果

- Budget contract
- StopDecision contract
- stop reason taxonomy
- 两阶段 stop control flow
- budget/step 更新不变量

权威 Budget/Stop specification 见
[`../docs/08_agent_controller.md`](../docs/08_agent_controller.md)；公共 enum 和
StopDecision invariants 见
[`../docs/00_shared_domain_schemas.md`](../docs/00_shared_domain_schemas.md)。

### P1-06 Decision Record

```text
Decision ID: P1-06
Status: Confirmed
Decision:
1. Phase 1 只使用一维 action budget：max_perception_actions >= 0，
   remaining_perception_actions = max_perception_actions - step。不得新增多维
   BudgetState、PerceptionCost 或 frame/token/latency/cost placeholder schema，
   也不修改 PerceptionResult 增加这些字段。真实 MLLM telemetry 留到对应阶段。
2. Zero-budget run 仍执行 cheap/static initialization 并构造 step-0 State，然后
   以 budget_exhausted 停止；不调用 Information Need、Value 或 Perceiver。
3. 调用 SegmentPerceiver.observe() 是 action 消费边界。succeeded、failed 和
   Perceiver declared exception 各消耗一次；pre/post stop 和 Perceiver 前的
   exception 不消耗，后续 updater exception 不重复消耗。无法发布 post-State
   时由 P1-07 terminal record 表达已消费 action，不伪造非法 State。
4. StopPolicy 暴露 decide_pre_value(state) 和
   decide_post_value(state, best_segment_value)。post-value 只接收 Controller
   确定性选出的最佳 SegmentValue，不接收完整 batch 或隐藏全局状态。
5. StopReason 固定为 budget_exhausted、ranking_sufficiently_certain、
   no_unobserved_segments、max_segment_value_too_low、component_failure 和
   safety_limit_reached。空/重复 candidate input 是启动前 ContractError。
6. ranking certainty 使用 configurable top1_top2_margin threshold，满足
   margin >= threshold 时停止；margin=None 时跳过。Low-value 使用 configurable
   minimum threshold，满足 best value < threshold 时停止。None 表示关闭相应
   可选 condition。
7. mock-v1 使用 max actions=2、ranking margin threshold=0.10、
   min segment value=0.15，确保 canonical 两步运行最终以 budget_exhausted
   停止；high-certainty override 使用 0.01，low-values 的最大值低于 0.15。
8. Terminal priority 为 safety_limit_reached > component_failure >
   budget_exhausted > no_unobserved_segments >
   ranking_sufficiently_certain > max_segment_value_too_low。正常 failed
   perception 本身不是 StopReason；提交 State 后由下一轮条件决定。
9. StopDecision continue 时 stop=False/reason=None/details={}；terminal 时
   stop=True/reason 必须存在。details 只保存结构化诊断信号，不能用自由文本
   reason 或隐藏字段驱动控制。各 StopReason 的精确 details keys 以
   docs/08_agent_controller.md 的 P1-01—P1-09 consistency correction 为准。
10. Phase 1 不增加 cancellation token 或 external_cancelled reason。同步
    interrupt 由 CLI/进程入口处理，async/service cancellation 留到未来讨论。
Rationale:
保持 Phase 1 的控制面只有一次一次的 perception action，使用透明、可配置的
margin/value thresholds 验证两阶段 stop mechanics；typed reason 和确定优先级
保证每个退出可测试、可回放。真实 MLLM 的 frames/tokens/latency 是后续实验
telemetry，不应在 Mock 阶段以空占位 schema 提前引入。
Alternatives considered:
多维 BudgetState；新增 PerceptionCost/usage telemetry；零预算时跳过 step-0
State；Mock boolean certainty/low-value signals；自由文本 reason；无优先级；
完整 Value batch 输入 StopPolicy；Phase 1 cancellation token。
Affected docs:
docs/00_shared_domain_schemas.md；docs/00_component_interfaces.md；
docs/08_agent_controller.md；docs/00_deterministic_mock_scenario.md；
P1-07 Trace/Result；P1-09 stop tests。
Deferred follow-up:
P1-07 已确认异常路径的 terminal attempted-action 字段和 StopDecision 在 trace
中的布局；Phase 4/真实 MLLM 阶段再讨论 processed frames、tokens、latency、
duration 等 telemetry。
Confirmed by: User
Date: 2026-07-31
```

---

## 9. P1-07 — Trace, Replay, and Reproducibility

Status: `Confirmed`

### 已确认范围

- 每个 run 固定保存 resolved config、JSONL trace 和独立 final result。
- 一次 decision-loop 一行，不使用细粒度 event stream。
- State 使用链式完整 snapshot，避免相邻 before/after 重复。
- 保存本轮全部轻量 SegmentValue，不保存 Tensor/raw payload。
- seed、data version、component descriptors 和 Git 状态进入 Result。
- 正式 replay 读取已保存 artifacts，不重新调用 components。
- deterministic Mock re-execution 是独立测试。
- TraceWriter failure 中断 Agent。
- Phase 1 只记录 synthetic/pseudonymous data。

### AgentStepTrace 字段

- schema/run/decision identity
- chained state before/after
- Information Need
- all candidate Segment Values
- selected SegmentMeta and SegmentValue
- PerceptionResult
- action-consumed flag
- terminal StopDecision
- JSON metadata

明确不增加 timing/cost placeholders、raw response、feature Tensor 或每行重复的
component versions。

### P1-07 的交付结果

- AgentStepTrace schema
- AgentRunResult schema
- JSONL layout
- run-directory layout
- deterministic replay definition

权威 specification 见
[`../docs/00_trace_replay.md`](../docs/00_trace_replay.md)。

### P1-07 Decision Record

```text
Decision ID: P1-07
Status: Confirmed
Decision:
1. 每个 run 使用 runs/<run_id>/resolved_config.json、trace.jsonl 和 result.json，
   不新增 manifest。普通 run ID 为 UTC timestamp 加 8 位随机十六进制，不包含
   业务 ID；canonical golden run ID 固定为 mock-v1-golden。已有目录不得静默
   覆盖。
2. Resolved config 使用 P1-09 固定的 canonical JSON bytes，保存单父继承合并和
   validation 后的完整 typed configuration，保留显式 null，不保存 secret；
   P1-08 runner 在 Controller 前原子写入。
3. Trace 每次 decision-loop 一行，不拆成 event stream。Controller initialization
   declared failure 允许在 loop 前写唯一一条 terminal record。Canonical mock-v1
   为两条 completed action records 加一条 pre-value budget stop，共三行。
4. Trace 使用完整但链式的 State：第一条保存 state_before，每次合法 transition
   保存 state_after，后续 current State 从上一条 state_after 得到且不重复保存
   state_before。Zero-budget/first-terminal record 保存 step-0 State；Result
   额外保留一份 final State 方便独立读取。
5. AgentStepTrace 只保存 schema/run/decision identity、chained States、
   InformationNeed、全部 SegmentValues、selected SegmentMeta/SegmentValue、
   PerceptionResult、action_consumed、terminal StopDecision 和 metadata。不增加
   TraceOutcome、StopStage 或 AgentError schema。
6. Value Model 被调用后保存所有轻量 SegmentValue，以验证 coverage、argmax、
   tie-break 和 low-value stop。Controller 按复合 identity 验证并归一化到
   `(item_id, segment_id)` canonical input order 后再写 trace。Tensor、embedding、
   media 和 raw MLLM output 不内嵌，只使用已有 ResourceRef；不增加 timing/cost
   placeholders。
7. AgentRunResult 保存 success flag、final State、terminal StopDecision、
   attempted actions、trace count、seed、data version、component descriptors、
   git commit/dirty 和 metadata。Final ranking 从 final State 派生，不重复存储；
   declared error 使用 StopDecision.details。
8. Result 中 seed、data/fixture version、component descriptors 和 Git fields
   必须存在；Git metadata 无法获得时允许 null，dirty run 明确标记。Descriptors
   按 P1-08 config role 固定顺序保存；selector ID 与 runtime descriptor ID 分离。
9. 正式 replay 读取 resolved config、trace 和 result，顺序重建并验证 State
   chain、budget、selection、Evidence/Observation、stop 和 Result，不重新调用
   components，也不重新计算真实模型 score。
10. Deterministic Mock re-execution 是独立测试；使用相同 resolved config、
    seed、固定 run ID 和固定 nullable test Git metadata，要求 trace/result 精确
    一致。普通 run 仍记录真实 Git metadata。
11. TraceWriter 暴露 write_step 和 write_result。每条 record validation 后以
    canonical UTF-8/LF JSONL 写入并 flush；任何 write failure 抛
    ComponentExecutionError 并终止 run。Writer 自身 failure 不要求再写 terminal
    record/result，不返回 AgentRunResult；result 使用原子目标文件写入，失败不能
    报告成功或留下半截正式 result.json。
12. Phase 1 只使用 synthetic Mock users，不保存 raw history、secret、绝对媒体
    路径或 stack trace。TraceWriter 不 hash/修改 State；真实用户数据脱敏在
    进入真实数据阶段前单独确认。
Rationale:
用最少三个 artifacts 完整记录每次控制决策。链式 State 避免相邻快照重复，
逐行 flush 避免内存随 run 增长；全量轻量 SegmentValue 保留决策审计能力，而
Tensor/raw payload 继续通过 references 隔离。Saved-output replay 不会在未来
意外重调真实 MLLM。
Alternatives considered:
event-based JSONL；每行重复 before/after State；State summary/delta schema；
只保存最大 SegmentValue；inline Tensor/raw output；额外 manifest；
TraceOutcome/AgentError schema；replay 重新执行 components；trace failure 后
继续 Agent；timing/cost placeholders。
Affected docs:
docs/00_trace_replay.md；docs/00_shared_domain_schemas.md；
docs/00_component_interfaces.md；docs/08_agent_controller.md；
docs/00_deterministic_mock_scenario.md；P1-08 run bootstrap；P1-09 golden/replay
tests。
Resolved follow-up:
P1-08 已确认 run directory creation、resolved config writer、TraceWriter ownership
和 CLI failure reporting。
Deferred follow-up:
P1-09 固化 trace/replay/re-execution test matrix；真实 per-run
candidate-segment 规模经 profiling 证明 inline values 存在 I/O 问题后，再讨论
artifact/reference，不提前加入。
Confirmed by: User
Date: 2026-07-31
```

---

## 10. P1-08 — Configuration, Bootstrap, and CLI

Status: `Confirmed`

CLI 是薄入口；核心 Agent 必须可以被 Python 直接调用。
本 Gate 只确认配置加载、组件组装和运行入口，不改变 P1-01—P1-07 已确认的
Agent 算法、状态机、Stop semantics 或 Trace/Result contract。

### 已确认范围

- `base.yaml`、`mock.yaml` 和 experiment config 使用单父配置确定性继承。
- PyYAML 只解析 YAML，Pydantic v2 负责 strict/frozen typed validation。
- component 只通过稳定 implementation ID 和显式 constructor mapping 选择。
- 配置内路径使用规范化项目相对路径；`extends` 相对声明它的 YAML。
- `mock-v1` run input 和查表数据来自 versioned fixture JSON。
- Controller 使用单个 strict/frozen `AgentRunRequest`。
- fixture loader、bootstrap、runner、Controller 和 CLI 各自保持单一职责。
- CLI 只调用共享 `run_from_config()`，不复制组装、持久化或 Agent loop。
- run directory 独占创建，不覆盖已有输出；resolved config 在 Controller 前写入。
- exit code、stderr 和 unexpected exception 行为固定。

### 必须保持的边界

```text
CLI
→ call shared run_from_config(...)
→ load/validate config and fixture
→ create run directory and write resolved config
→ bootstrap components
→ call AgentController.run(AgentRunRequest(...))
→ report the TraceWriter-persisted result
```

CLI 中不能实现 Information Need、Value selection、Score Update 或 Stop Policy。

### P1-08 的交付结果

- config layout
- typed config contract
- bootstrap responsibility
- Python API example
- CLI invocation and output convention

### 已确认 Python API

底层调用接收已经完成 validation、run identity 和目录准备的输入：

```python
controller = build_controller(
    config=config,
    fixture=fixture,
    run_dir=run_dir,
)

result = controller.run(
    AgentRunRequest(
        run_id=run_id,
        user_id=user_id,
        user_history=history,
        candidate_ids=candidate_ids,
    )
)
```

高层实验入口统一完成外围 lifecycle：

```python
result = run_from_config("configs/mock.yaml")
```

CLI 只调用这个高层入口。

### P1-08 Decision Record

```text
Decision ID: P1-08
Status: Confirmed
Decision:
1. Phase 1 保留 configs/base.yaml、configs/mock.yaml 和 configs/experiments/。
   配置只支持一个相对路径 extends，可以形成 experiment → mock → base 链；loader
   必须按规范化文件路径检测循环。Mapping 递归合并，scalar 和 list 整体替换，
   不做 list merge，也不支持 CLI key=value overrides。extends 不进入最终 typed
   config；完整合并结果写入 resolved_config.json。
2. 不引入第三方配置框架。YAML 使用 PyYAML.safe_load() 解析，最终合并 object
   使用 Pydantic v2 strict、frozen、extra="forbid" models 验证。Phase 1 不使用
   Hydra、OmegaConf、DI framework、environment-variable interpolation、Python
   class import strings 或自动 plugin discovery；实现阶段才把 Pydantic v2 和
   PyYAML 加入 dependencies。
3. Phase 1 typed config 顶层固定为 schema_version、seed、data_version、run、
   agent、stop、components 和 input。run 保存 output_root/run_id；agent 只保存
   max_perception_actions；stop 保存可空 ranking_margin_threshold 和
   min_segment_value；input 保存 fixture_path。不增加 timing、cost、token、frame
   或真实模型参数。schema_version 固定为 "1"；seed 是非负 int；data_version
   是非空字符串；max_perception_actions 是非负 int；ranking_margin_threshold
   是 null 或非负 finite float；min_segment_value 是 null 或 finite float，允许为
   负。run ID 和路径也必须显式验证；可用 component ID 按 role 限定，未知 ID
   直接拒绝。
4. Phase 1 config selector ID 固定使用 mock、in_memory、default、threshold 和
   jsonl 等稳定短 ID。Bootstrap 对每个 role 使用显式 match 或 constructor
   mapping；runtime ComponentDescriptor 使用独立、显式、稳定的 implementation
   ID，不通过 reflection 生成。以后新增真实实现时显式增加 selector、descriptor
   和 constructor，不允许 arbitrary import path 或隐式 discovery。
5. --config 相对 shell working directory 解析。项目根目录是配置文件祖先中包含
   pyproject.toml 的目录；找不到时启动失败。extends 必须是相对当前 YAML 文件
   的路径，整个 extends chain 必须留在同一项目根目录。配置内部
   fixture_path/output_root 必须是留在项目根目录内的规范化项目相对路径，
   Phase 1 拒绝绝对路径和通过 .. 或 symlink 逃逸项目根目录的路径。
   resolved_config.json 只保存规范化项目相对路径，不保存本机绝对路径。
6. mock.yaml 只通过 input.fixture_path 指向
   tests/fixtures/mock/v1/scenario.json。user_id、history、candidate_ids 和全部
   Mock 查表数据保存在该 versioned JSON 中，不内嵌 YAML，也不拆成大量 CLI
   flags。Runner 在创建 run directory 前加载并验证 fixture 一次，并验证 fixture
   version 与 config.data_version 一致；Bootstrap 接收这个已验证 fixture，不得
   再次读取。
7. Controller run input 收敛为 strict/frozen AgentRunRequest(run_id, user_id,
   user_history, candidate_ids)。Controller.run(request) 在 terminal trace/result
   成功写入时返回 AgentRunResult；TraceWriter failure 传播异常且不返回 Result。
   Budget、stop thresholds、seed、data version、components、descriptors 和可获得
   的 Git metadata 在构造 Controller 时注入，不在 Request 中重复。Request、
   resolved config、State、Trace 和 Result 的实际 run ID 必须一致。
8. Bootstrap 接收 validated config、已验证 fixture、run directory 和所需 runtime
   metadata；显式实例化全部 Protocol implementations，将同一个 fixture object
   传给相关 Mock components，创建绑定 run directory 的 TraceWriter，按 typed
   config role 固定顺序收集并验证 component descriptors，再构造 AgentController。
   Bootstrap 不执行 loop、不计算 Need/Value、不选 segment、不修改 State、不实现
   Stop Policy，也不使用 global singleton 或 service locator。
9. Python 提供两层调用。底层 build_controller(...) 返回使用相同公共契约的
   AgentController，调用方显式传入 AgentRunRequest；高层 run_from_config(...)
   负责 load/merge/validate config、一次性 fixture load、run ID/directory、resolved
   config、Git metadata 收集和 bootstrap，然后调用同一个 Controller API。CLI
   只调用 run_from_config()，不复制第二套流程。Trace/result 仍由 Controller 通过
   注入的 TraceWriter 写入；runner 只负责 resolved config 和最终报告。
10. Phase 1 只提供 python -m pave_rec.cli.run_mock --config configs/mock.yaml，
    以及可选 --run-id mock-v1-golden。不添加 console script、交互式菜单或其他
    research-parameter overrides。成功时 stdout 报告 run_id、output directory、
    stop reason 和从 final State 派生的 final ranking。
11. Run lifecycle 固定为：load/merge config → validate config → load/validate
    fixture once → determine actual run ID → exclusively create run directory → write
    resolved_config.json → bootstrap → Controller.run。--run-id 的显式值优先于
    config.run.run_id；两者都为空时自动生成 P1-07 格式的 ID。显式 ID 必须符合
    P1-07 允许的普通格式或 mock-v1-golden。已有显式 ID 报错且不覆盖；自动 ID
    碰撞时重新生成。实际 ID 通过构造新的 frozen resolved config 写回
    resolved_config.json，并进入 AgentRunRequest/State/Trace/AgentRunResult。
12. Config/fixture/input validation 在创建 run directory 前失败，exit code=2 且
    不产生 Agent artifacts。Bootstrap constructor failure 是 startup failure，
    不伪装成 Agent decision；因为它发生在目录和 resolved config 已安全落盘后，
    可以留下仅含 resolved_config.json 的失败 run directory，但不能伪造
    trace.jsonl、result.json 或 StopDecision。Controller initialization component
    failure 在 Writer 健康时写无 State 的 terminal trace/result；TraceWriter
    failure 使用 P1-09 特殊边界。其他 Controller runtime failure 遵守
    P1-05—P1-07。CLI exit code 固定为：0 表示
    完整写入且
    AgentRunResult.succeeded=True；1 表示 startup constructor、runtime、component
    或 artifact/trace failure；2 表示 CLI/config/fixture/input validation failure；
    130 表示 KeyboardInterrupt。Declared error 向 stderr 输出简洁诊断；unexpected
    programming exception 保留 Python traceback，但 stack trace 不写入持久化产物。
Typed config shape:
schema_version: "1"
seed: 7
data_version: mock-v1
run: {output_root: runs, run_id: null}
agent: {max_perception_actions: 2}
stop: {ranking_margin_threshold: 0.10, min_segment_value: 0.15}
components:
  user_memory: mock
  initial_ranker: mock
  item_feature_store: in_memory
  segment_store: in_memory
  state_builder: default
  information_need: mock
  segment_value: mock
  perceiver: mock
  evidence_updater: mock
  observation_updater: mock
  score_updater: mock
  stop_policy: threshold
  trace_writer: jsonl
input: {fixture_path: tests/fixtures/mock/v1/scenario.json}
Rationale:
用一个很小、确定、可审计的父配置机制支持 Phase 1 Mock 和后续实验，同时通过
typed validation、显式 constructor mapping 和共享 Python runner 防止配置系统、
CLI 或 bootstrap 形成第二套 Agent 逻辑。Fixture 只加载一次，run directory 在任何
Agent action 前固定，resolved config 保存实际 run ID，使 trace/result 的运行身份
和复现实验输入一致。
Alternatives considered:
单个重复配置文件；Hydra/OmegaConf composition；多父配置；CLI key=value
overrides；list merge；environment interpolation；class import strings；plugin
discovery；配置相对 cwd；保存绝对路径；YAML 内嵌 fixture；大量 input flags；
Controller 使用多个 run 参数；CLI 自己组装/持久化；覆盖已有 run directory；
bootstrap failure 伪装成 Agent StopDecision。
Affected docs/tests:
todo/implementation_roadmap.md；docs/00_component_interfaces.md；
docs/08_agent_controller.md；docs/00_trace_replay.md；
docs/00_deterministic_mock_scenario.md；configs/README.md；P1-09 config/bootstrap/
CLI/integration tests。
Deferred follow-up:
P1-09 固化 inheritance/merge/cycle/path/config validation、fixture one-load、run ID
collision、exit code 和 Python/CLI equivalence tests；Phase 2 在真实 data/store
配置进入前重新确认外部 dataset/artifact path policy；安装后的 console command、
真实 secret 注入、多个 config groups 和动态 experiment overrides 留到确有需求时
讨论。
Confirmed by: User
Date: 2026-08-01
```

---

## 11. P1-09 — Test Matrix and Phase Acceptance

Status: `Confirmed`

### Unit Tests

必须覆盖：

- config inheritance/merge/cycle detection、strict validation 和 path rules
- schema validation and serialization
- deterministic reranking and tie-breaking
- State build/rebuild
- observed/unobserved segment bookkeeping
- budget updates
- stop reason precedence
- evidence append/update behavior
- score-prior preservation invariant
- trace/replay chain、selection 和 action-accounting validators
- declared-exception partial-progress semantics
- budget-derived safety guard

### Integration Tests

- User Memory → Recommendation State
- State → Information Need
- State/Need/Segments → Segment Value
- selected segment → Evidence
- Evidence → Score Update
- Score Update → State rebuild
- Controller → Trace Writer
- validated config/fixture → bootstrap → Controller
- Python `run_from_config()` 与 CLI 使用同一运行路径
- Perceiver、Updater、ScoreUpdater 和 TraceWriter fault injection

### End-to-End Tests

- standard multi-step Mock run
- zero-budget run
- no-unobserved-segment run
- ranking-certainty stop
- low-value stop
- normal failed-perception continuation
- declared component-failure paths
- saved-output deterministic replay
- exact deterministic Mock re-execution
- explicit run-ID collision without overwrite
- CLI success/failure exit codes and output channels
- bootstrap failure and partial-artifact behavior

### Phase 1 验收标准

- 同一输入、配置和 seed 得到相同结果。
- segment 不会被重复观察。
- 每次 Perceiver attempt（成功或失败）恰好按确认规则更新 budget 和 step。
- 未观察 item 保留有意义的 initial ranking prior。
- 每一步都产生符合契约的 Recommendation State。
- 每个退出路径都有结构化 stop reason。
- JSONL trace 足以完成确认定义下的 replay。
- Controller 只依赖接口。
- 所有真实研究算法仍为 Mock、Deferred 或 TBD。
- Canonical golden run 的 resolved config、trace 和 result 精确稳定。
- 测试离线、CPU-only，并且只向 pytest 临时目录写 run artifacts。
- `pytest`、Ruff 和已确认的 branch coverage gate 全部通过。
- GitHub Actions 的已确认 Python/OS matrix 全部通过。

### P1-09 的交付结果

- 最终测试矩阵
- Phase 1 Definition of Done
- 允许进入实现和验收的明确边界

### P1-09 Decision Record

```text
Decision ID: P1-09
Status: Confirmed
Decision:
1. Phase 1 使用 unit、integration 和 end-to-end 三层测试。每条已确认的 Schema、
   interface、Controller transition、Stop condition、artifact lifecycle 和 CLI
   contract 都必须至少在最贴近其 ownership 的层级拥有明确断言；不能只用一个
   happy-path E2E test 代替边界测试。
2. 本阶段质量门固定为 pytest 全部通过、Phase 1 implementation modules 的
   branch coverage 至少 90%，并通过 Ruff lint 和 format check。Phase 1 暂不把
   mypy 或其他静态类型检查器加入 Definition of Done，避免扩大工具链范围。
3. GitHub Actions 属于 Phase 1 Definition of Done。CI matrix 固定覆盖 Ubuntu 上
   Python 3.10/3.12，以及 Windows 上 Python 3.12；所有 jobs 必须通过。
4. Canonical mock-v1 在 pytest 临时 synthetic project root 的 run directory 中
   执行，并与纳入版本控制的
   resolved_config.json、trace.jsonl 和 result.json 做 byte-exact golden
   comparison。三个 artifacts 使用 P1-07 canonical serializer；Golden 使用固定
   run ID 和固定 nullable Git metadata。正式
   saved-output replay 只读取 artifacts 并做 schema/chain/decision semantic
   validation；exact deterministic Mock re-execution 是独立测试。
5. budget_exhausted、ranking_sufficiently_certain、no_unobserved_segments、
   max_segment_value_too_low、component_failure 和 safety_limit_reached 六个
   StopReason 都必须覆盖。Safety guard 可以通过直接注入越界 iteration count 的
   unit test 覆盖，不要求在合法 Agent flow 中人为制造无限循环。
6. Failure matrix 必须区分 Controller initialization component failure、normal
   failed PerceptionResult、Perceiver declared exception、ObservationUpdater
   failure、EvidenceUpdater failure、ScoreUpdater failure、TraceWriter step
   failure 和 result failure，并断言各自的 action accounting、last valid State、
   partial progress、trace/result 和 CLI exit code。
7. TraceWriter failure 是 artifact sink 的特殊失败边界。write_step 失败后立即
   停止且不得执行后续 action；已经成功 flush 的 records 保留，不要求已经损坏的
   Writer 再记录自己的 terminal record。write_result 使用原子目标文件写入；失败
   时不得留下看似完整的 result.json。两种 Writer failure 都不能返回/报告成功的
   AgentRunResult，Python API 传播 ComponentExecutionError，CLI 返回 1。
8. Config/path tests 必须覆盖 inheritance、merge、cycle、unknown fields/IDs、
   absolute path、.. escape、project-root detection 和 run-ID collision。Symlink
   escape 在运行平台允许创建 symlink 时执行；不支持的环境显式 skip，其他 path
   contract 仍为必测项。
9. 所有自动化测试必须 offline、CPU-only，不调用网络、真实 MLLM、GPU 或外部
   dataset。Integration/E2E 在 pytest `tmp_path` 下建立包含 pyproject、configs、
   fixture 和 runs 的最小 synthetic project root；配置路径仍严格为 root 内相对
   路径。测试不写入或清理仓库真实 runs/。
10. Phase 1 完成要求：全部本地 quality gates 和 CI matrix 通过；canonical
    artifacts 可精确复现；saved-output replay 通过；README、稳定 docs、配置和
    实现一致；仓库中仍不包含被误写死的真实研究算法。
11. P1-09 Confirmed 表示 Phase 1 的设计与验收门已经关闭，可以开始实现；它不
    表示 Phase 1 已经完成。只有上述 Definition of Done 全部满足后，路线图中的
    Phase 1 才能标记 Completed。
Rationale:
Phase 1 的目标是证明完整 Agent harness 的确定性、状态正确性和可回放性。分层
测试、精确 golden、独立 replay、全部 partial-progress fault paths 和跨平台 CI
共同防止 happy-path-only、仅本机可运行或 artifact 不完整却误报成功。
Alternatives considered:
只运行 pytest happy path；不设 coverage/lint gate；只在本机测试；只测试一个
通用 component exception；将 replay 与 re-execution 混为一体；Writer 失败后
继续 action；要求损坏的 Writer 记录自身失败；在测试中写仓库 runs/；Phase 1
立即引入 mypy 或真实模型 smoke tests。
Affected schemas/interfaces:
AgentController, TraceWriter, replay validators, config/bootstrap/runner/CLI and all
confirmed Phase 1 component contracts. No new research schema is introduced.
Affected docs/tests:
docs/00_trace_replay.md；todo/implementation_roadmap.md；Phase 1 unit/integration/
e2e/golden tests；GitHub Actions workflow；quality-tool configuration。
Deferred follow-up:
真实 MLLM integration、network/GPU tests、timing/cost telemetry、mypy adoption、
真实 dataset paths 和 performance/load tests 在对应后续 Phase 再确认。
Confirmed by: User
Date: 2026-08-01
```

### P1-01—P1-09 Cross-Gate Consistency Record

```text
Decision ID: P1-XG-01
Status: Confirmed
Decision:
1. Segment identity 统一为 (item_id, segment_id)；segment_id 只在所属 item 内
   唯一。任何全局 candidate-segment coverage、selection、tie-break 和 replay 都
   使用复合 identity。
2. Config selector ID 与 ComponentDescriptor.implementation 分离。前者选择显式
   constructor，后者标识实际 runtime implementation；descriptor tuple 使用固定
   config role 顺序和 docs/00_deterministic_mock_scenario.md 3.5 的版本表。
3. resolved config、trace 和 result 使用 docs/00_trace_replay.md 的唯一 canonical
   UTF-8/LF JSON contract。JSON keys、collection order、explicit null、file-ending
   newline 和 golden checkout line endings 全部固定；仓库增加 .gitattributes。
4. StopDecision.details 使用 docs/08_agent_controller.md 的按 reason 精确 key
   contract。CandidateSegment/SegmentValue、State candidates、catalog segments、
   Evidence 和 component descriptors 使用各自已记录的 canonical order。
5. 普通业务/运行时 declared exception 在 TraceWriter 健康时写 terminal
   trace/result。TraceWriter 自身 failure 是特殊 artifact-sink 边界：立即停止、
   保留此前成功 records、传播 ComponentExecutionError、不返回 Result。
6. Config/input validation、Bootstrap constructor、Controller initialization
   component 和 TraceWriter failure 使用四种明确的 artifact lifecycle；Controller
   initialization failure 的 terminal record 无 State、action_consumed=false。
7. P1-09 的临时 artifacts 不放宽 P1-08 path contract。E2E 使用 pytest tmp_path
   内的 synthetic project root，fixture/output 仍为 root 内规范化相对路径。
8. docs/09 的第一条 preprocessing baseline 属于 Phase 2；docs/01 和 docs/02
   的真实 User Memory/SASRec 属于 Phase 3；docs/06 的真实 MLLM 和 cost logging
   属于 Phase 4；docs/05 的 supervised Segment Value 属于 Phase 5。Phase 1
   不实现或预留这些真实算法/telemetry 字段。
Rationale:
消除九个 Gate 之间会让 validator、golden、exception handling 或测试 root 产生
两种合法解释的工程歧义，同时不改变任何研究算法、Mock 数值、状态机主顺序、
预算或 Stop semantics。
Affected docs/tests:
docs/00_shared_domain_schemas.md；docs/00_component_interfaces.md；
docs/00_deterministic_mock_scenario.md；docs/00_trace_replay.md；
docs/08_agent_controller.md；docs/02_sasrec_initial_ranking.md；
docs/06_mllm_perception.md；configs/README.md；todo/implementation_roadmap.md；
Phase 1 schema/interface/controller/config/trace/golden/failure tests。
Confirmed by: User
Date: 2026-08-01
```

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
