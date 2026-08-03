# Module 04 — Information Need Estimation
# 推荐信息需求估计模块

## 1. 模块目标 Purpose

判断：

```text
为了改善当前推荐决策，现在最缺什么推荐相关信息？
```

Information Need 在 segment selection 之前，**不能预先绑定某一个 item**。

错误例子：

```text
Does item A contain a plot twist?
```

更合理的形式：

```text
当前 ranking 不确定，
用户很在意 plot twists，
但现有 evidence 还不足以区分领先候选。
```

---

## 2. 输入 Input

```text
Recommendation State
```

重点使用：

- user preference atoms
- top competing candidates
- current evidence
- ranking uncertainty

---

## 3. 输出 Output

公共输出以
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md) 为准：

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
```

例如：

```json
{
  "need_id": "need_001",
  "concept": "narrative surprise",
  "description": "Evidence about whether a candidate contains strong plot twists",
  "relevant_preference_atom_ids": ["atom_plot_twist"],
  "preference_importance": 0.91,
  "evidence_gap": 0.82,
  "ranking_relevance": 0.88,
  "contrastiveness": null,
  "embedding_ref": null,
  "metadata": {}
}
```

---

## 4. Conceptual Formula

一个可能的概念表达：

```text
NeedValue(k)
=
PreferenceImportance(k)
× EvidenceGap(k)
× RankingRelevance(k)
× Contrastiveness(k)
```

注意：

这还不是最终研究公式，只是当前设计 intuition。

---

## 5. Implementation Staging

Phase 1 只使用 deterministic `MockInformationNeedEstimator` 验证接口和数据流，
不实现或默认任何真实 Information Need 算法。

Phase 3 负责产生可供本模块消费的真实 `UserMemoryView`，并确认 atom、match、drift、
embedding/matrix refs 的 Information Need readiness；Phase 3 不实现真实 estimator，
也不根据 Memory 单独推断 evidence gap 或 ranking relevance。

Phase 4 在 MLLM prompt/perception 之前必须通过独立 Gate 确认第一条真实 rule-based
baseline。该 Gate 至少讨论：

1. 获取 top user preference atoms
2. 判断 top competing candidates 在哪些 preference dimensions 上 evidence 很弱
3. 优先选择最能影响候选区分的维度

Rule-based estimator 是候选 baseline，不是已经确认的最终研究选择。
Learned estimator 只在 Phase 6 完成 baseline evaluation 后作为 Phase 7 optional
advanced research 讨论。

Interface：

```python
class InformationNeedEstimator(Protocol):
    def estimate(
        self,
        state: RecommendationState,
    ) -> InformationNeed:
        ...
```

跨组件接口的权威定义见
[`00_component_interfaces.md`](00_component_interfaces.md)。

Implementations：

```text
MockInformationNeedEstimator
RuleBasedInformationNeedEstimator
LearnedInformationNeedEstimator
```

---

## 6. Important Constraint

不要：

```text
先选 item
再找它的 segment
```

正确顺序：

```text
Recommendation State
      ↓
Information Need
      ↓
evaluate all relevant unobserved (item, segment) pairs
      ↓
Segment Value Model
```

这样当前排第二的 item 才有机会因为一个高价值 segment 被优先观察，并在后续超过 top1。

---

## 7. TBD

- exact need vocabulary
- whether needs come from preference atoms directly
- whether an LLM generates normalized semantic needs
- whether need estimation is learned
- exact formula for importance / evidence gap / contrastiveness
