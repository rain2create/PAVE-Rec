# Module 00 — Shared Domain Schemas
# 共享领域对象与序列化约定

## 1. Purpose

`src/pave_rec/domain/` 定义 Agent Controller、模型接口、Store、Trace 和测试共同
使用的稳定领域对象。它只表达业务语义和 references，不依赖任何具体模型、
Tensor framework、数据库或外部服务。

本文档是公共 Domain Schema 的唯一权威定义。01—10 模块文档可以描述模块内部
状态和概念示例，但凡跨模块传递的对象都以本文档为准。

公共 schema 使用 Pydantic v2 strict、frozen models，并禁止未声明字段。下方
代码块为了突出字段而省略 `BaseModel`、`ConfigDict` 和 validators。实现应等价
于：

```python
model_config = ConfigDict(
    extra="forbid",
    frozen=True,
    strict=True,
)
```

Updater 返回新对象，不原地修改已经发布的 domain object。

---

## 2. Common Conventions

- 所有 ID 是非空 `str`。
- item、user、atom、evidence、need 和 run 等 ID 在各自 owning collection 中按
  对应 contract 保持唯一。Segment 的完整身份始终是
  `(item_id, segment_id)`；`segment_id` 只要求在同一个 item 内唯一，不要求在
  不同 items 之间全局唯一。
- 事件时间使用 Unix epoch milliseconds，并显式命名为 `*_at_ms`。
- 行为顺序在需要时使用非负 `interaction_index`。
- `None` 表示未提供、不可用或尚未计算。
- 空 collection 表示已经计算但结果为空。
- `T | None` 字段默认 `None`，持久化时保留为显式 `null`；语义 collection
  由构造者显式提供，不能用默认空值掩盖“尚未计算”。
- score 和 expected value 是 finite float，不默认属于 `[0, 1]`。
- rank 从 1 开始；step、budget 和 attempt counters 从 0 开始。
- strength、persistence 和 confidence 属于 `[0, 1]`。
- cosine similarity 属于 `[-1, 1]`。
- domain object 和 metadata 必须 JSON compatible。

文档中的 `JsonObject` 表示键为 `str` 的 JSON-compatible object。Pydantic 的
`frozen=True` 只阻止字段重新赋值，不会自动深度冻结嵌套 JSON container。因此
Phase 1 实现必须在 validation 时复制 JSON payload，并将其视为只读；任何更新
都通过构造新 domain object 完成，不能原地修改 `metadata`、`attributes` 或
`details`。

标准 JSON round trip 使用 Pydantic v2 `model_dump(mode="json",
exclude_none=False)` 与对应 JSON validation API；不能依赖 Python pickle 作为
公共 Domain 的持久化格式。

Phase 1 的持久化 tuple 使用以下 canonical ordering：

- `InitialRankingOutput.candidates` 按显式 `rank` 排列。
- `RecommendationState.candidates` 按 `current_rank` 排列。
- 每个 item 的 catalog segments 按 `(start_ms, end_ms, segment_id)` 排列；对应的
  proxy refs、observation snapshots 和 unobserved IDs 保持同一相对顺序。
- Evidence 按成功 acquisition/append 顺序排列，关联的 evidence IDs 保持同序。
- Controller 投影的 `CandidateSegmentRef` 按 `(item_id, segment_id)` 排列；trace
  中的 `SegmentValue` 在 identity coverage validation 后归一化到同一顺序。

JSON object key order、文件编码和换行由
[`00_trace_replay.md`](00_trace_replay.md) 的 canonical serialization contract
统一定义。

domain 中不允许：

```text
Tensor
ndarray
model
tokenizer
Store
file handle
arbitrary Python object
```

这些资源通过 `ResourceRef` 关联；具体实现负责解析 reference 和构建模型 batch。

Phase 1 已确认的 Enum：

```text
PreferenceState     = stable | emerging | fading | inactive
PreferenceMatchType = stable | emerging | fading
ObservationStatus   = unobserved | succeeded | failed
StopReason          = budget_exhausted
                    | ranking_sufficiently_certain
                    | no_unobserved_segments
                    | max_segment_value_too_low
                    | component_failure
                    | safety_limit_reached
```

---

## 3. References

```python
class ResourceRef:
    store: str
    key: str
    version: str
    checksum: str | None
```

`ResourceRef` 可以指向 feature、embedding、Similarity Matrix、媒体、原始模型
响应或其他 artifacts。`store/key/version` 必须足以在一次可复现实验中解析到
确定资源，但 portable ref 不拥有机器 root binding。P2 filesystem loader 必须另外由
trusted validated root registry 构造；exact release ref 是 portable identity handoff，
不是携带 absolute path 的自包含 locator。

公共 Schema 保持 `checksum: str | None`，以兼容 Phase 1 Mock refs 和未来
non-filesystem Stores。P2-03 对 Phase 2 filesystem source/generated resources
施加更严格的 `sha256:<64 lowercase hex>` required-checksum contract；这属于具体
resolver/manifest validation，不改变 `ResourceRef` 的公共 shape。

精确 `size_bytes` 不重复加入每个公共 ref：P2-03 通过
`DataIdentity.source_artifacts` 和 `RootBundleManifest.artifacts` 中的 typed
`ArtifactEntry` 保存 checksum/size inventory。P2-06 filesystem resolver 只解析该
release inventory 声明的 refs；同一 root 下未声明的文件不是隐式合法资源。

---

## 4. User Memory

```python
class PreferenceAtomView:
    atom_id: str
    text: str
    state: PreferenceState
    strength: float
    persistence: float
    created_at_ms: int | None
    last_seen_at_ms: int | None
    embedding_ref: ResourceRef | None
    metadata: JsonObject


class PreferenceMatchView:
    long_atom_id: str | None
    short_atom_id: str | None
    similarity: float | None
    classification: PreferenceMatchType


class UserMemoryView:
    long_term_atoms: tuple[PreferenceAtomView, ...]
    short_term_atoms: tuple[PreferenceAtomView, ...]
    preference_matches: tuple[PreferenceMatchView, ...]
    global_drift: float | None
    new_interest_drift: float | None
    drop_interest_drift: float | None
    semantic_profile: str | None
    similarity_matrix_ref: ResourceRef | None
    memory_version: str
    updated_at_ms: int | None
    metadata: JsonObject
```

`PreferenceMatchView` 的两个 atom ID 不能同时为 `None`。完整 Matrix 不进入
Recommendation State；Information Need 使用 match/drift 派生信号，learned
implementation 可以按 reference 加载 Matrix。

`PreferenceState` 描述 atom 的 `stable/emerging/fading/inactive` 状态；
`PreferenceMatchType` 只描述派生 match signal 的 `stable/emerging/fading`，
避免把 `inactive` 错当成一次 Long × Short match classification。

---

## 5. Ranking and Segments

```python
class InitialRankedCandidate:
    item_id: str
    score: float
    rank: int


class InitialRankingOutput:
    candidates: tuple[InitialRankedCandidate, ...]
    user_sequence_feature_ref: ResourceRef | None
    metadata: JsonObject


class SegmentMeta:
    item_id: str
    segment_id: str
    start_ms: int
    end_ms: int
    media_ref: ResourceRef
    metadata: JsonObject


class SegmentProxyRef:
    item_id: str
    segment_id: str
    feature_ref: ResourceRef
    metadata: JsonObject
```

`end_ms` 必须大于 `start_ms`。P2-04 投影的 SegmentMeta 使用相对于
`media_ref` 自身的 half-open `[start_ms, end_ms)`：独立 clip 使用其
local `[0, duration_ms)`，原媒体 range 使用声明的起止时间。独立
clip 的原视频 provenance 可以不存在；它不是 Phase 1 SegmentMeta 的必需
字段。这是 Phase 2 的兼容投影规则，不改变 Phase 1 schema shape。

Initial ranking 使用有显式 rank 的 candidate entries，不分别维护可能互相矛盾的
score map 和 ranking list。

---

## 6. Evidence and Observation

```python
class Evidence:
    evidence_id: str
    item_id: str
    segment_id: str
    attributes: JsonObject
    text_summary: str | None
    confidence: float | None
    source: str
    raw_output_ref: ResourceRef | None
    embedding_ref: ResourceRef | None
    metadata: JsonObject


class SegmentObservationState:
    item_id: str
    segment_id: str
    status: ObservationStatus
    attempt_count: int
    evidence_ids: tuple[str, ...]
    failure_reason: str | None
    last_attempt_step: int | None


class ItemEvidenceState:
    item_id: str
    evidence: tuple[Evidence, ...]
    aggregated_attributes: JsonObject
    evidence_embedding_ref: ResourceRef | None


class EvidenceState:
    items: tuple[ItemEvidenceState, ...]


class ItemObservationState:
    item_id: str
    segment_observations: tuple[SegmentObservationState, ...]


class ObservationState:
    items: tuple[ItemObservationState, ...]
```

Phase 1 的 `ObservationStatus` 是 `unobserved`、`succeeded` 或 `failed`。
Evidence 只保存 JSON-compatible structured attributes；原始响应和 embedding
使用 reference。

运行时 Evidence 与 Observation 分开保存：`EvidenceState` 只负责有效证据，
`ObservationState` 是 segment attempt/status 的唯一事实来源。
`RecommendationStateBuilder` 从二者生成 candidate snapshot。

---

## 7. Recommendation State

```python
class RankingUncertainty:
    top1_top2_margin: float | None


class CandidateState:
    item_id: str
    initial_score: float
    current_score: float
    initial_rank: int
    current_rank: int
    segment_observations: tuple[SegmentObservationState, ...]
    unobserved_segment_ids: tuple[str, ...]
    evidence: ItemEvidenceState
    item_feature_ref: ResourceRef | None
    segment_proxy_refs: tuple[SegmentProxyRef, ...]


class RecommendationState:
    schema_version: str
    run_id: str
    user_id: str
    user_memory: UserMemoryView
    candidates: tuple[CandidateState, ...]
    max_perception_actions: int
    remaining_perception_actions: int
    step: int
    ranking_uncertainty: RankingUncertainty
    metadata: JsonObject
```

State 保存全部 candidates，并满足：

```text
remaining_perception_actions = max_perception_actions - step
```

---

## 8. Agent Decisions

```python
class InformationNeed:
    need_id: str
    concept: str
    description: str
    relevant_preference_atom_ids: tuple[str, ...]
    preference_importance: float | None
    evidence_gap: float | None
    ranking_relevance: float | None
    contrastiveness: float | None
    embedding_ref: ResourceRef | None
    metadata: JsonObject


class CandidateSegmentRef:
    item_id: str
    segment_id: str
    item_feature_ref: ResourceRef | None
    segment_proxy_ref: ResourceRef | None


class SegmentValueInput:
    state: RecommendationState
    information_need: InformationNeed
    candidate_segments: tuple[CandidateSegmentRef, ...]


class SegmentValue:
    item_id: str
    segment_id: str
    value: float
    metadata: JsonObject


class StopDecision:
    stop: bool
    reason: StopReason | None
    details: JsonObject
```

加载 references 后产生的 Tensor batch 属于具体 Segment Value implementation，
不属于 `SegmentValueInput`。

---

## 9. Cross-object Invariants

Phase 1 Schema implementation 必须验证：

- `ResourceRef.store/key/version` 均为非空字符串。
- 同一 owning collection 中 item、atom 和 evidence ID 不重复；segment 使用复合
  identity `(item_id, segment_id)`，同一 item 内不允许重复 segment ID。
- Initial/current rank 从 1 开始、连续且唯一；candidate 顺序与显式 rank 一致。
- `InitialRankingOutput`、`RecommendationState` 和各 Store snapshot 中的
  candidate/item identity 一致。
- `EvidenceState` 和 `ObservationState` 中每个 tuple entry 的 `item_id`
  与所属 candidate 一致。
- `CandidateState.segment_observations` 和 `unobserved_segment_ids` 都是
  `ObservationState` 的派生快照，不能成为独立事实来源。
- `unobserved` observation 的 `attempt_count == 0` 且无 Evidence；
  `succeeded` 至少关联一个同 item/segment 的 Evidence；`failed` 保存明确的
  failure reason，并且不伪造 Evidence。
- `SegmentMeta.end_ms > start_ms`；跨 item 可以复用同名 segment ID，但同一 item
  下 segment ID 必须唯一。
- `remaining_perception_actions == max_perception_actions - step`，且三者非负。
- `RankingUncertainty.top1_top2_margin` 在存在时是 finite 且非负。
- `StopDecision.stop=False` 时 `reason=None`；`stop=True` 时 reason 必须存在。
- StopDecision 的 `details` 必须 JSON-compatible，不能通过自由文本 reason
  替代 `StopReason` enum。

Trace/Result 的跨字段 invariants 留到 P1-07。

---

## 10. Trace and Results

```python
class AgentStepTrace:
    schema_version: str
    run_id: str
    decision_index: int
    state_before: RecommendationState | None
    information_need: InformationNeed | None
    segment_values: tuple[SegmentValue, ...] | None
    selected_segment: SegmentMeta | None
    selected_segment_value: SegmentValue | None
    perception_result: PerceptionResult | None
    state_after: RecommendationState | None
    action_consumed: bool
    stop_decision: StopDecision | None
    metadata: JsonObject


class AgentRunResult:
    schema_version: str
    run_id: str
    succeeded: bool
    final_state: RecommendationState | None
    stop_decision: StopDecision
    attempted_perception_actions: int
    trace_record_count: int
    seed: int
    data_version: str
    component_descriptors: tuple[ComponentDescriptor, ...]
    git_commit: str | None
    git_dirty: bool | None
    metadata: JsonObject
```

两个对象都是 frozen、strict、JSON-serializable 顶层 schema，并带显式
`schema_version`。`PerceptionResult` 和 `ComponentDescriptor` 的权威定义见
[`00_component_interfaces.md`](00_component_interfaces.md)。

Trace 使用链式 State：第一条拥有 State 的 record 保存 `state_before`，每次合法
transition 保存新的 `state_after`，后续 record 不重复保存相同 State。完整字段
presence、run-directory 和 replay invariants 见
[`00_trace_replay.md`](00_trace_replay.md)。

Trace/Result validators 至少检查：

- `decision_index` 非负，同一 trace 中从 0 连续递增。
- Trace、嵌套 State 和 Result 的 `run_id` 一致。
- `selected_segment` 与 `selected_segment_value` 的 item/segment identity 一致。
- `action_consumed` 与正常 State step transition 或 terminal attempted-action
  accounting 一致。
- 正常 completed run 必须有 final State；component/safety failure 的
  `succeeded=False`。
- Result 的 final State、terminal StopDecision、attempted actions 和 trace
  record count 与 JSONL chain 一致。

---

## 11. Ownership

```text
domain/enums.py
domain/refs.py
domain/memory.py
domain/ranking.py
domain/segments.py
domain/evidence.py
domain/state.py
domain/decisions.py
domain/trace.py
domain/serialization.py
domain/interface_types.py
```

`domain/__init__.py` 只导出稳定公共类型。模型、Store、Controller、Updater 和
CLI 不能在 domain 中放置实现逻辑。P1-03 Request/Result、component descriptor
以及 P1-08 `AgentRunRequest` 的定义见
[`00_component_interfaces.md`](00_component_interfaces.md)。
