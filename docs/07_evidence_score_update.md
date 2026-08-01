# Module 07 — Evidence State and Score Update
# 证据状态与推荐分数更新模块

## 1. 模块目标 Purpose

每次 MLLM perception 后：

```text
new multimodal evidence
      ↓
update item evidence state
      ↓
update recommendation score
      ↓
rerank
```

这个模块目前刻意保持抽象，因为 score update 的最终研究设计还没有完全锁死。

---

## 2. Evidence State

公共 Evidence/Observation Schema 以
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md) 为准：

```python
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

Evidence 和 Segment Observation 是不同概念。Phase 1 的每个 segment 使用：

```text
unobserved
succeeded
failed
```

`succeeded` 表示已经获得有效的结构化 Evidence；`failed` 表示 Perceiver 已经
被调用但没有产生有效 Evidence。失败仍消耗一次 perception action，Phase 1
不自动重试。

运行时 `ObservationState` 是 observation records 的唯一事实来源；
`EvidenceState` 只保存成功产生的 Evidence。Segment Store 只保存静态
metadata；Recommendation State 中的 observation 和 unobserved segment
列表都是 Builder 构造的只读派生快照。

State 和 Score Updater 只消费轻量结构化 Evidence。原始 MLLM response、完整
API response、媒体、frame 和 Evidence embedding 存在 artifacts/Store 中，并
通过 reference 关联；保存这些内容不代表将它们加入 MLLM prompt。

---

## 3. Evidence Update

Required API：

```python
class EvidenceUpdater(Protocol):
    def update(
        self,
        state: EvidenceState,
        evidence: Evidence,
    ) -> EvidenceState:
        ...


class ObservationUpdater(Protocol):
    def update(
        self,
        state: ObservationState,
        result: PerceptionResult,
        attempt_step: int,
    ) -> ObservationState:
        ...
```

P1-03 已确认两个 updater 都是纯状态转换并返回新对象。EvidenceUpdater 只处理
成功 Evidence；ObservationUpdater 处理 succeeded/failed attempt。P1-05 已确认
`attempt_step = current RecommendationState.step + 1`，与 post-action State
中的 `step` 相同。权威接口见
[`00_component_interfaces.md`](00_component_interfaces.md)。

V1 可以简单做：

```text
append evidence
+
aggregate duplicate attributes
```

---

## 4. Score Update — 当前尚未最终确定

目前保留两个主要方向。

### Option A — Residual Update

```text
new_score_i
=
initial_score_i
+
delta_score_i
```

其中：

```text
delta_score_i =
f(
    user_state,
    evidence_i,
    current_state
)
```

优点：

- 保留 conventional recommender prior
- active perception gain 比较容易解释

### Option B — Unified Reranker

```text
user_state
+
cheap item features
+
observed evidence
      ↓
reranker
      ↓
new score
```

优点：

- 更灵活
- 可以做 richer fusion

当前工程需要支持统一 interface，但不要替研究设计做最终选择。

---

## 5. API

```python
class ScoreUpdater(Protocol):
    def update(
        self,
        request: ScoreUpdateRequest,
    ) -> tuple[CandidateScore, ...]:
        ...
```

`ScoreUpdateRequest` 同时携带 initial ranking prior 和 previous scores；输出必须
覆盖全部 candidates。接口定义见
[`00_component_interfaces.md`](00_component_interfaces.md)。

Implementations：

```text
MockScoreUpdater
ResidualScoreUpdater
UnifiedEvidenceRanker
```

第一版端到端 loop 只要求：

```text
MockScoreUpdater
```

---

## 6. Reranking

```python
def rerank(scores: dict[str, float]) -> list[str]:
    return [
        item_id
        for item_id, _ in sorted(
            scores.items(),
            key=lambda pair: (-pair[1], pair[0]),
        )
    ]
```

每次 update 之后都重新构建 `RecommendationState`；相同 score 使用稳定的
`item_id` 次序打破并列。

---

## 7. Critical Requirement

没有被观察的 item 仍然必须保留有意义的 score。

不要因为只观察了部分 item，就把整个 ranking 重置成只依赖 perceived items。

除非后续最终 score-update 方法明确学习了这一点，否则：

```text
SASRec prior
```

应该贯穿整个 Agent loop。

---

## 8. TBD

- residual vs unified reranker
- evidence aggregation
- evidence embedding method
- training targets
- whether evidence changes only the selected item's score or all candidates
