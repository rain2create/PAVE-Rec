# Module 05 — Segment Value Model
# Recommendation-aware Segment Expected Value Model

## 1. 模块目标 Purpose

这是整个研究里最核心的模块之一。

它预测：

```text
如果现在花一次昂贵 perception action 去看这个未观察 segment，
它预计能给当前 recommendation decision 带来多大的改善？
```

它不是普通的：

```text
Query-Segment Relevance
```

核心建模目标是：

```text
Expected Recommendation Gain
```

---

## 2. 输入 Input

对每一个：

```text
(item_i, segment_j)
```

使用：

```text
User Preference State
+
Current Recommendation State
+
Information Need
+
Item Cheap Features
+
Segment Cheap Proxy Features
```

---

## 3. 输出 Output

公共输出以
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md) 为准：

```python
class SegmentValue:
    item_id: str
    segment_id: str
    value: float
    metadata: JsonObject
```

Agent 选择：

```text
argmax_(item, segment) value(item, segment)
```

---

## 4. Important Behavior

例如当前：

```text
A = 0.81
B = 0.79
C = 0.61
```

Information Need：

```text
plot twist / narrative surprise
```

Value prediction：

```text
V(A, seg1) = 0.12
V(A, seg2) = 0.31

V(B, seg1) = 0.45
V(B, seg2) = 0.17

V(C, seg1) = 0.03
```

应该：

```text
select B.seg1
```

也就是说：

`Segment Value Model` 必须跨 item 比较所有候选 segment，而不是先固定 item。

---

## 5. Feature Interface

跨模块输入只携带 State、Information Need 和带版本的 feature references。
具体 implementation 加载 reference 后可以构造 Tensor batch，但不把 Tensor
写回公共 Domain Schema。

```python
class CandidateSegmentRef:
    item_id: str
    segment_id: str
    item_feature_ref: ResourceRef | None
    segment_proxy_ref: ResourceRef | None


class SegmentValueInput:
    state: RecommendationState
    information_need: InformationNeed
    candidate_segments: tuple[CandidateSegmentRef, ...]
```

---

## 6. Model API

P1-03 已确认 synchronous batch interface：

```python
class SegmentValueModel(Protocol):
    def predict(
        self,
        request: SegmentValueInput,
    ) -> tuple[SegmentValue, ...]:
        ...
```

输出必须与输入 candidate segments 一一对应，不允许 duplicate、missing 或
extra item/segment。权威错误契约见
[`00_component_interfaces.md`](00_component_interfaces.md)。

Implementations：

```text
MockSegmentValueModel
SupervisedSegmentValueModel
```

---

## 7. Training Principle

第一阶段先做 supervised learning。

V1 不要求 RL。

Label generation 的总体逻辑：

```text
current ranking
      ↓
actually perceive segment
      ↓
extract new evidence
      ↓
update item score
      ↓
new ranking
      ↓
measure recommendation gain
```

Potential label components：

```text
ΔNDCG
ΔMRR
Δrank(target item)
Δtop-k correctness
Δranking margin
regret reduction
```

精确定义当前：

```text
TBD
```

---

## 8. Dataset Generation

Offline label builder 应该支持：

```python
for state in sampled_recommendation_states:
    for unobserved_segment in candidate_segments:
        before = evaluate_ranking(state)

        evidence = oracle_or_mllm_perceive(unobserved_segment)
        new_state = simulate_update(state, evidence)

        after = evaluate_ranking(new_state)

        gain = compute_gain(before, after)

        save(
            state_features,
            segment_proxy_features,
            gain,
        )
```

因为这一步可能计算昂贵，所以应该 offline 完成。

---

## 9. V1 Architecture

不要锁死研究 architecture。

可以支持：

```text
MLP over fused dense features
small Transformer / attention fusion
pairwise ranker
```

推荐开发顺序：

```text
Mock model
→ simple MLP
→ richer architecture if needed
```

---

## 10. Loss

当前保留：

```text
TBD
```

可以预留：

```text
regression loss
pairwise ranking loss
listwise loss
```

---

## 11. Future RL

只有 supervised system 稳定之后，再考虑 RL。

未来 objective 可以类似：

```text
ranking quality gain
-
perception cost
```

但 RL 不属于 V1 必需项。

---

## 12. TBD

- exact expected-gain label
- oracle generation method
- model architecture
- loss
- negative sampling
- value uncertainty
- whether stop action enters the same policy
