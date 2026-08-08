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

P4-ARCH-02 已确认：最终 proposed Segment Value Model 是 ≤1B 判别式多模态 Segment Selector。它直接为完整
Top-100 内全部 eligible segments 输出 value，不把 P4-04 Chinese-CLIP relevance 作为前置 shortlist。
Chinese-CLIP 规则只保留为 bootstrap/baseline；proposed Selector 使用自己版本化的 vision/token compression path。

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
MultimodalSegmentSelector
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

其中 `before` 与 `after` 必须由同一冻结版本的 raw-frame Evidence pipeline + native-frame 约 8B MLLM
Candidate Reranker 计算；两次都从固定 SASRec base scores 与完整当前 EvidenceState 纯函数式重算。Artifact
中分开保存 raw gain 与 cost，训练时再组合，以便重画不同成本权重的 budget curve。ΔNDCG、ΔMRR、rank
change 作为辅助分析，不作为第一版唯一 label。第一版先固定 Reranker 再训练 Selector，不联合更新两者。

---

## 8. Dataset Generation

Offline label builder 应该支持：

```python
for state in sampled_recommendation_states:
    for unobserved_segment in stratified_label_segments:
        before = evaluate_ranking(state)

        evidence = load_or_publish_selected_frame_evidence(unobserved_segment)
        new_state = simulate_update(state, evidence)

        after = frozen_native_frame_mllm_reranker(new_state)

        gain = compute_gain(before, after)

        save(
            state_features,
            segment_proxy_features,
            gain,
        )
```

因为一次 label 需要约 8B Reranker forward，所以应该 offline 完成。Label builder 不要求对每个 state 的全部约
1200 segments 穷举；采用按 item rank、Query relation、target/non-target、segment duration/content diversity、
random/hard negative 分层的 configurable subset，并报告每个 state 的 label coverage。Selector 推理时仍覆盖
全部 eligible segments。

必须先按 user/time 划分数据，再在各 split 内生成 observation states、deep evidence cache 与 value labels；同一基础 case 的反事实 variants 不得跨 split。target 只用于 offline label 构造，不进入 online Value Model 输入。

---

## 9. First Multimodal Selector Architecture (Phase 5)

P4-ARCH-02 已确认 proposed family，但 exact 规模/vision tower/token count 仍通过 P5 Gate 与 validation 确定：

该任务不同于常见“在一个视频内部挑关键帧/关键 clip”的 selector。PAVE-Rec 的输入是 Top-100 多个视频，
每个视频又包含数量可变的 segments；目标是在当前用户、Query、候选竞争和已有 Evidence 条件下，对全部
`(item, segment)` 做跨视频全局比较，最终只选择一个 segment。Frame attention 只是构造 segment 表示的局部步骤，
不是最终选择目标。

```text
per-segment low-resolution multi-frames
    → Selector-owned lightweight vision tower/tokenizer
    → content-only compact frame tokens（versioned/cacheable）
    → Query/Memory-conditioned local resampler
    → one segment token per eligible segment
    → within-item segment context（shared item/rank/score token）
    → cross-item global segment set/listwise scorer
    → one scalar expected value per segment
```

关键约束：

- 无独立 CLIP shortlist；全部 eligible segments 必须得到一一对应输出；
- 不把最多数千 raw images 拼进一个语言模型上下文；local frame encoding/compression 与 global segment scoring
  分层执行，全局层目标只处理约 1200 个 segment-level tokens；
- content-only tokens 可跨用户复用，但 Query-conditioned segment representation 和 value 不可跨用户复用；
- 每个 segment 保留多帧 compact tokens 后再根据当前 Query 压缩，不能离线无条件平均成一个固定向量；
- 模型必须编码 frame timestamp、segment position/duration、item grouping、item SASRec rank/score、variable segment
  mask 和 observed status，避免把同一视频内局部重要性误当成跨候选 recommendation value；
- 输入继续包含 Memory、SASRec score/rank、item/segment identity/position、Information Need 和 observation state；
- 模型是判别式 scalar scorer，不生成解释文本或 score JSON；
- ≤1B 是上限级研究目标，不预先锁死必须使用 1B；100M/300M/500M/1B scale 属于 P6 cost-quality ablation。

推荐训练顺序：

```text
freeze selector vision tower + cached content tokens
→ train query/state fusion and scalar head
→ optional unfreeze last vision blocks on sampled raw frames
→ freeze final selector and rebuild canonical token cache
```

MLP over fixed proxy features、small attention selector 和 P4 Query-relevance 继续作为容量/selection baselines，
不等于 proposed multimodal Selector。

---

## 10. Loss

V1 支持 pointwise regression 到 expected-gain label，并增加同一 Recommendation State 内的 pairwise/listwise
ordering loss；具体权重由 validation-only tuning 决定。未标注的 segment 不当作零 gain，使用 masked partial-label
loss。可增加 teacher-score distillation 和 value-uncertainty head，但第一版不加入 joint Reranker gradients 或 RL。

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
- exact Selector model/vision tower/size/token compression architecture
- loss
- counterfactual label sampling/hard negatives
- value uncertainty
- whether stop action enters the same policy
- alternating/joint Selector-Reranker training（P6/P7 only）
