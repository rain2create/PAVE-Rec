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

```python
@dataclass
class InformationNeed:
    need_id: str
    concept: str
    description: str
    preference_importance: float | None
    evidence_gap: float | None
    ranking_relevance: float | None
    contrastiveness: float | None
    embedding: Tensor | None
    metadata: dict
```

例如：

```json
{
  "concept": "narrative surprise",
  "description": "Evidence about whether a candidate contains strong plot twists",
  "preference_importance": 0.91,
  "evidence_gap": 0.82,
  "ranking_relevance": 0.88
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

## 5. V1 Implementation

V1 先支持一个简单 estimator。

可以：

1. 获取 top user preference atoms
2. 判断 top competing candidates 在哪些 preference dimensions 上 evidence 很弱
3. 优先选择最能影响候选区分的维度

第一版可以是 rule-based。

Interface：

```python
class InformationNeedEstimator:
    def estimate(
        self,
        state: RecommendationState,
    ) -> InformationNeed:
        ...
```

Implementations：

```text
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
