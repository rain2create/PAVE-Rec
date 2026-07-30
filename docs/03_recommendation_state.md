# Module 03 — Recommendation State
# 推荐状态模块

## 1. 模块目标 Purpose

`Recommendation State` 是 Agent 当前时刻能看到的核心运行状态。

它应该汇总：

- 当前用户偏好状态
- 当前候选 item score / ranking
- 已经观察过哪些多模态 evidence
- 剩余 perception budget
- 当前 ranking uncertainty

---

## 2. Core Schema

```python
@dataclass
class CandidateState:
    item_id: str
    current_score: float
    rank: int

    observed_segment_ids: list[str]
    unobserved_segment_ids: list[str]

    evidence: dict
    cheap_features: dict


@dataclass
class RecommendationState:
    user_id: str
    user_memory: UserMemoryState
    candidates: list[CandidateState]
    remaining_budget: int
    step: int
    ranking_uncertainty: dict
    metadata: dict
```

---

## 3. Initial Construction

输入：

```text
Dynamic User Preference State
+
SASRec candidate scores
+
candidate cheap features
+
segment metadata
+
empty evidence state
```

输出：

```text
RecommendationState(step=0)
```

---

## 4. Ranking Uncertainty

V1 保持简单。

默认先用：

```text
Top1 - Top2 margin
```

例如：

```text
A = 0.81
B = 0.79

margin = 0.02
```

margin 很小说明 top candidates 之间 ranking conflict 较强。

未来可以加入：

```text
top1_top2_margin
topk_score_std
normalized score entropy
ensemble disagreement
```

但是 V1 只要求 margin。

---

## 5. State Update

每执行一次 perception 后：

```text
new evidence
      ↓
item evidence update
      ↓
score update
      ↓
rerank
      ↓
mark selected segment observed
      ↓
decrement budget
      ↓
rebuild Recommendation State
```

---

## 6. Required API

```python
class RecommendationStateBuilder:
    def build(
        self,
        user_state,
        candidate_ids,
        current_scores,
        evidence_state,
        remaining_budget,
        step,
    ) -> RecommendationState:
        ...
```

---

## 7. Logging

每一个 loop step 都应该保存：

```text
step
candidate scores
candidate ranking
ranking margin
information need
segment values
selected segment
MLLM evidence
updated scores
remaining budget
stop reason
```

这些 trace 后续用于：

- debugging
- paper case studies
- ablations
- agent behavior visualization

---

## 8. TBD

- richer uncertainty formulation
- whether uncertainty should be learned
- candidate disagreement features
