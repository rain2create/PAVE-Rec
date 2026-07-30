# Module 08 — Agent Controller and Stop Policy
# Agent 控制器与停止策略

## 1. 模块目标 Purpose

负责协调完整的 active-perception loop。

`AgentController` 本身不要塞太多研究逻辑。

研究逻辑应该分别放在：

- Information Need Estimator
- Segment Value Model
- Stop Policy
- Score Updater

Controller 只负责 orchestrate。

---

## 2. Controller API

```python
class AgentController:
    def run(
        self,
        user_id: str,
        user_history: list[str],
        candidate_ids: list[str],
    ):
        ...
```

---

## 3. Runtime Loop

```python
user_state = user_memory.build_or_update(user_history)

scores = initial_ranker.score(
    user_id,
    user_history,
    candidate_ids,
)

evidence_state = EvidenceState.empty(candidate_ids)

budget = max_budget
step = 0

while True:
    state = state_builder.build(
        user_state=user_state,
        candidate_ids=candidate_ids,
        current_scores=scores,
        evidence_state=evidence_state,
        remaining_budget=budget,
        step=step,
    )

    decision = stop_policy.should_stop(state)
    if decision.stop:
        break

    need = information_need_estimator.estimate(state)

    segments = segment_store.get_unobserved_segments(
        candidate_ids,
        evidence_state,
    )

    values = segment_value_model.predict(
        state,
        need,
        segments,
    )

    selected = max(values, key=lambda x: x.value)

    if stop_policy.should_stop_after_value(
        state,
        selected.value,
    ).stop:
        break

    evidence = perceiver.observe(
        item_id=selected.item_id,
        segment_id=selected.segment_id,
        information_need=need,
        user_state=user_state,
        current_evidence=evidence_state,
    )

    evidence_state = evidence_updater.update(
        evidence_state,
        evidence,
    )

    scores = score_updater.update(
        user_state,
        candidate_features,
        scores,
        evidence_state,
    )

    budget -= 1
    step += 1

return rerank(scores)
```

---

## 4. Stop Policy

V1 支持：

```text
STOP if:
remaining_budget == 0
OR
ranking_margin >= threshold
OR
max_segment_value < threshold
OR
no unobserved segments remain
```

Interface：

```python
@dataclass
class StopDecision:
    stop: bool
    reason: str
```

---

## 5. Trace Logging

每一步都写 structured trace：

```python
@dataclass
class AgentStepTrace:
    step: int
    ranking_before: list[str]
    scores_before: dict[str, float]
    information_need: dict | None
    segment_values: list[dict] | None
    selected_segment: dict | None
    evidence: dict | None
    scores_after: dict[str, float] | None
    ranking_after: list[str] | None
    remaining_budget: int
    stop_reason: str | None
```

建议每次运行保存 JSONL。

---

## 6. Reproducibility

每次 run 需要保存：

- config snapshot
- random seed
- model checkpoints
- dataset version
- user id
- candidate ids
- agent trace

---

## 7. V1

第一版可以使用：

```text
real or mock user memory
real or mock SASRec
rule-based information need
mock value model
mock perceiver
mock score updater
simple stop policy
```

主要目标是先验证 loop。

---

## 8. TBD

- whether stop is predicted by a learned policy
- whether segment selection and stop become a unified action space
- whether RL later controls the entire loop
