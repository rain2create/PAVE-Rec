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

```python
@dataclass
class ItemEvidenceState:
    item_id: str
    evidence_list: list[Evidence]
    aggregated_attributes: dict
    evidence_embedding: Tensor | None


@dataclass
class EvidenceState:
    items: dict[str, ItemEvidenceState]
```

---

## 3. Evidence Update

Required API：

```python
class EvidenceUpdater:
    def update(
        self,
        evidence_state: EvidenceState,
        new_evidence: Evidence,
    ) -> EvidenceState:
        ...
```

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
class ScoreUpdater:
    def update(
        self,
        user_state,
        candidate_features,
        previous_scores,
        evidence_state,
    ) -> dict[str, float]:
        ...
```

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
    return sorted(scores, key=scores.get, reverse=True)
```

每次 update 之后都重新构建 `RecommendationState`。

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
