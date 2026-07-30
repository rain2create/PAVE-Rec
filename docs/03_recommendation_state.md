# Module 03 — Recommendation State
# 推荐状态模块

## 1. 模块目标 Purpose

`Recommendation State` 是 Agent 某一决策时刻的只读完整快照。

它应该汇总：

- 当前用户偏好状态
- 全部候选 item 的 initial/current score 和 ranking
- segment observation status 和已经获得的结构化 evidence
- 最大和剩余 perception action 数量
- 当前 ranking uncertainty

State 只能由 `RecommendationStateBuilder` 构造。Controller 和其他组件维护
独立的运行时 scores、Evidence/Observation State 和 action counters，但不能
原地修改已经构造的 State。每次 perception action 后都重新构造新快照。

---

## 2. Core Schema

下面表示已经确认的 State contract；具体 dataclass/validated-model 类型和字段
校验在 P1-02 中确定。

```python
@dataclass
class CandidateState:
    item_id: str

    initial_score: float
    current_score: float
    initial_rank: int
    current_rank: int

    segment_observations: list[SegmentObservationState]
    unobserved_segment_ids: list[str]

    evidence: ItemEvidenceState
    item_feature_ref: str | None
    segment_proxy_refs: dict[str, str]


@dataclass
class RecommendationState:
    schema_version: str
    run_id: str
    user_id: str

    user_memory: UserMemoryView
    candidates: list[CandidateState]

    max_perception_actions: int
    remaining_perception_actions: int
    step: int

    ranking_uncertainty: dict
    metadata: dict
```

State 保存全部 candidates。ranking 是显式快照，按 `current_score` 降序排列；
相同 score 使用稳定的 `item_id` 次序打破并列。

`UserMemoryView`、Evidence 和 Observation 只包含紧凑的结构化信息。Tensor、
embedding、Similarity Matrix、原始媒体、原始 MLLM response 和完整 API
response 必须放在 Store 或 artifacts 中，并通过带版本的 reference 关联。

`unobserved_segment_ids` 是根据静态 Segment Store 和运行时 observation status
计算出的快照，不是独立事实来源。

---

## 3. Initial Construction

输入：

```text
Dynamic User Preference State
+
SASRec candidate scores
+
candidate/segment feature references
+
segment metadata
+
empty Evidence/Observation State
```

输出：

```text
RecommendationState(step=0)
```

---

## 4. Ranking Uncertainty

Phase 1 只保存一个原始 signal：

```text
Top1 - Top2 margin
```

例如：

```text
A = 0.81
B = 0.79

margin = 0.02
```

margin 很小说明 top candidates 之间 ranking conflict 较强。少于两个 candidate
时 margin 为 `None`，对应的 stop/error 语义在 P1-06 中确定。

未来可以加入：

```text
top1_top2_margin
topk_score_std
normalized score entropy
ensemble disagreement
```

Phase 1 的 stop threshold 配置化，但 margin 不代表最终 uncertainty 研究设计。

---

## 5. State Update

`step` 从 0 开始，表示当前 run 已经发起的 perception action 数量。Stop check、
Information Need estimation 和 Segment Value prediction 不增加 step；调用
Perceiver 后 step 增加 1，成功和失败调用都消耗一次 action。

始终满足：

```text
remaining_perception_actions = max_perception_actions - step
```

每执行一次 perception action 后：

```text
observation succeeded / failed
      ↓
update runtime Observation State
      ↓
append Evidence and update score if succeeded
      ↓
rerank if scores changed
      ↓
increment step / decrement remaining actions
      ↓
rebuild Recommendation State
```

Phase 1 中 failed segment 不自动重试。真实 MLLM 的 retry/repair 和多维成本留到
Phase 4 讨论。

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
        observation_state,
        max_perception_actions,
        remaining_perception_actions,
        step,
        run_id,
    ) -> RecommendationState:
        ...
```

具体参数对象和 ownership 在 P1-02/P1-03 中确定。

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
remaining perception actions
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
- real-MLLM retry and repair policy
- token, frame, duration, latency, and monetary budgets
