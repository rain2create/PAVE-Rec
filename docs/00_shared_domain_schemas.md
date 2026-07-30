# Module 00 — Shared Domain Schemas
# 共享领域对象与序列化约定

## 1. Purpose

`src/pave_rec/domain/` 定义 Agent Controller、模型接口、Store、Trace 和测试共同
使用的稳定领域对象。它只表达业务语义和 references，不依赖任何具体模型、
Tensor framework、数据库或外部服务。

公共 schema 使用 strict、frozen Pydantic models，并禁止未声明字段。Updater
返回新对象，不原地修改已经发布的 domain object。

---

## 2. Common Conventions

- 所有 ID 是非空 `str`。
- 事件时间使用 Unix epoch milliseconds，并显式命名为 `*_at_ms`。
- 行为顺序在需要时使用非负 `interaction_index`。
- `None` 表示未提供、不可用或尚未计算。
- 空 collection 表示已经计算但结果为空。
- score 和 expected value 是 finite float，不默认属于 `[0, 1]`。
- rank 从 1 开始；step、budget 和 attempt counters 从 0 开始。
- strength、persistence 和 confidence 属于 `[0, 1]`。
- cosine similarity 属于 `[-1, 1]`。
- domain object 和 metadata 必须 JSON compatible。

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
确定资源。

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
    metadata: dict


class PreferenceMatchView:
    long_atom_id: str | None
    short_atom_id: str | None
    similarity: float | None
    classification: PreferenceState


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
    metadata: dict
```

`PreferenceMatchView` 的两个 atom ID 不能同时为 `None`。完整 Matrix 不进入
Recommendation State；Information Need 使用 match/drift 派生信号，learned
implementation 可以按 reference 加载 Matrix。

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
    metadata: dict


class SegmentMeta:
    item_id: str
    segment_id: str
    start_ms: int
    end_ms: int
    media_ref: ResourceRef
    metadata: dict


class SegmentProxyRef:
    item_id: str
    segment_id: str
    feature_ref: ResourceRef
    metadata: dict
```

`end_ms` 必须大于 `start_ms`。Initial ranking 使用有显式 rank 的 candidate
entries，不分别维护可能互相矛盾的 score map 和 ranking list。

---

## 6. Evidence and Observation

```python
class Evidence:
    evidence_id: str
    item_id: str
    segment_id: str
    attributes: dict
    text_summary: str | None
    confidence: float | None
    source: str
    raw_output_ref: ResourceRef | None
    embedding_ref: ResourceRef | None
    metadata: dict


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
    aggregated_attributes: dict
    evidence_embedding_ref: ResourceRef | None
    segment_observations: tuple[SegmentObservationState, ...]


class EvidenceState:
    items: dict[str, ItemEvidenceState]
```

Phase 1 的 `ObservationStatus` 是 `unobserved`、`succeeded` 或 `failed`。
Evidence 只保存 JSON-compatible structured attributes；原始响应和 embedding
使用 reference。

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
    segment_proxy_refs: dict[str, ResourceRef]


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
    metadata: dict
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
    metadata: dict


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
    metadata: dict


class StopDecision:
    stop: bool
    reason: StopReason | None
    details: dict
```

`StopReason` 在 P1-06 确认。加载 references 后产生的 Tensor batch 属于具体
Segment Value implementation，不属于 `SegmentValueInput`。

---

## 9. Trace and Results

`AgentStepTrace` 和 `AgentRunResult` 是 frozen、strict、JSON-serializable
顶层 schema，并带显式 `schema_version`。它们的完整字段和持久化布局在
P1-07 确认。

---

## 10. Ownership

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
```

`domain/__init__.py` 只导出稳定公共类型。模型、Store、Controller、Updater 和
CLI 不能在 domain 中放置实现逻辑。
