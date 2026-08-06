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

### 4.1 Phase 4 confirmed pure Query-relevance baseline

P4-04 不训练 expected-gain model，也不把 P4-03 已用于 Query 选择的 importance、candidate difference、
evidence gap、rank weight 或 request uncertainty 再次加入 segment 排序。给定 P4-03 发布的 exact
Chinese-CLIP query vector `q`，对每个 eligible unobserved segment 的 2/3 张 normalized proxy frame
vectors 计算：

```text
c_k = dot(q, f_k)
value(item, segment) = mean(top-2(c_1..c_m)),  m in {2, 3}
```

`SegmentValue.value` 就是该 raw cosine mean。在完整 Top-100 的全部 eligible segments 上取全局 argmax；
相同 value 使用既有 Controller identity tie-break。P4 固定 `min_segment_value=null`，只记录 value 分布，
rank/novelty/threshold/random comparators 留作 P6 selection ablation。P5 再以反事实 recommendation gain
训练真正的 supervised Segment Value Model。
P4-04 只继承当前 versioned three-frame proxy recipe；三帧数量和 25%/50%/75% 位置是 pipeline baseline，
不是本模块锁定的最终研究选择，后续变体必须使用不同 artifact identity 做独立消融。

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

进入 Phase 5 后，第一条真实 value-model baseline 先做 supervised learning。

Phase 5 不要求 RL；Phase 1 只实现查表的 MockSegmentValueModel。

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

辅助诊断 label components：

```text
ΔNDCG
ΔMRR
Δrank(target item)
Δtop-k correctness
Δranking margin
regret reduction
```

V1 主标签已确定为：

\[
y_{i,j}=\log p_{after}(i^*)-\log p_{before}(i^*)-\lambda C_{i,j}
\]

其中 `before` 与 `after` 必须由同一冻结版本的 Deep Segment Encoder + Small Candidate-aware Multimodal Reranker 计算；两次都从固定 SASRec base scores 与完整当前 EvidenceState 纯函数式重算。artifact 中分开保存 raw gain 与 cost，训练时再组合，以便重画不同成本权重的 budget curve。ΔNDCG、ΔMRR、rank change 作为辅助分析，不作为第一版唯一 label。

---

## 8. Dataset Generation

Offline label builder 应该支持：

```python
for state in sampled_recommendation_states:
    for unobserved_segment in candidate_segments:
        before = evaluate_ranking(state)

        evidence = load_or_encode_deep_segment_evidence(unobserved_segment)
        new_state = simulate_update(state, evidence)

        after = frozen_small_reranker(new_state)

        gain = compute_gain(before, after)

        save(
            state_features,
            segment_proxy_features,
            gain,
        )
```

因为这一步可能计算昂贵，所以应该 offline 完成。

必须先按 user/time 划分数据，再在各 split 内生成 observation states、deep evidence cache 与 value labels；同一基础 case 的反事实 variants 不得跨 split。target 只用于 offline label 构造，不进入 online Value Model 输入。

---

## 9. First Supervised Architecture (Phase 5)

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

V1 先支持 pointwise regression 到上述 expected-gain label，并增加同一 Recommendation State 内的 pairwise ordering loss；具体权重由 validation-only tuning 决定。

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

但 RL 不属于 Phase 5 的必需项。

---

## 12. TBD

- exact expected-gain label
- oracle generation method
- model architecture
- loss
- negative sampling
- value uncertainty
- whether stop action enters the same policy
