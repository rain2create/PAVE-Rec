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
  "ranking_relevance": null,
  "contrastiveness": 0.64,
  "embedding_ref": null,
  "metadata": {
    "need_score": 0.478
  }
}
```

---

## 4. Phase 4 Confirmed Candidate-Aware Baseline

Phase 4 P4-03 已确认 Information Need 必须加入当前候选差异：

```text
NeedScore(q)
=
ConceptImportance(q)
× CandidateDifference(q)
× EvidenceGap(q)
```

它不是先挑一个 item。流程为：

```text
Memory stable/emerging/fading atoms
    → canonical tag/full-category concepts（最多 32 个）
    → Chinese-CLIP query × Top-100 segment proxy frames
    → rank-weighted candidate difference per concept
    → select one item-agnostic Information Need
    → Segment Value selects one concrete item/segment
```

### 4.1 Concept vocabulary and importance

- concept 只来自 Memory source prototypes 的 canonical tags 和完整 category paths；首版不使用 title、
  LLM 改写或近义词合并；
- tag 必须至少覆盖 P3 train-only item vocabulary 中 5 个不同 items；category path 不设 minimum-df floor；
- atom importance 为 `strength * (0.5 + 0.5 * persistence)`；stable source 对 long/short importance 取平均；
- 只用 train-only vocabulary 的静态 P2 item metadata 计算
  `IDF=log((N+1)/(df+1))/log(N+1)`；concept importance 是 supporting sources 的
  `source_importance * idf` 最大值；
- 同一 atom 的多个 tags 不按 tag 数量平分 importance；按确定性顺序保留前 32 个 concepts；df floor、cap、
  P3 derived/train-vocabulary checksum、P2 item-feature version 和 IDF recipe 进入 immutable artifact identity。
  Validation/test 只读该 artifact，不按 candidates、target、future behavior 或 test inventory 重算。

### 4.2 CLIP operands and aggregation

P4-03 的 cosine 两侧必须来自同一个 pinned Chinese-CLIP space：

```text
fixed-template concept text
    → Chinese-CLIP text encoder → normalized 512-D query vector

segment frame
    → Chinese-CLIP image encoder → normalized 512-D image vector
```

首版固定 `OFA-Sys/chinese-clip-vit-base-patch16` revision
`36e679e65c2a2fead755ae21162091293ad37834`。BGE-M3 只服务 P3 Memory semantics，不能与 Chinese-CLIP
image vectors 直接计算 cosine。P4 baseline 直接使用 raw L2-normalized cosine，不做 per-query P90/P99、
z-score 或 null-state calibration；必须记录每个 Query 的 frame、segment、candidate support 和 Difference
分布。Calibration 作为 P6 对照实验，不进入第一条闭环。

`need-query-template-zh-v1`：

```text
tag:      这段视频是否主要展示了「{concept}」相关内容？
category: 这段视频是否属于「{concept}」相关内容？
fallback: 这段视频是否包含有助于区分当前候选的核心内容？
```

每个 final segment 使用段内 25%/50%/75% 的最多三张有效 proxy frames。无效目标帧按
`delta=min(250ms, 0.1*segment_duration)` 和 `0,-delta,+delta,-2delta,+2delta` 顺序在段内寻找替代帧；
去重/过滤后少于两张有效帧的 segment 不参与。Image vectors 使用 official 224×224 processor，发布为 FP32、
L2-normalized 512-D refs。
对 query `q`：

```text
segment_relevance(s,q) = mean(top-2 frame cosine)
candidate_support(i,q) = mean(top-2 segment relevance)
```

只有一个有效 segment 时 candidate support 使用该值；不使用 single max，以降低 segment-count bias。

### 4.3 Top-100 candidate difference

令 `E` 为 Top-100 中至少存在一个 proxy-complete segment 的 candidates。先在完整 Top-100 计算：

```text
u_i = (1 / current_rank_i) / sum_j(1 / current_rank_j)
proxy_rank_mass = sum_{i in E} u_i
```

只有 `|E|>=2` 且 `proxy_rank_mass>=0.50` 时才计算：

```text
w_i = (1 / current_rank_i) / sum_{j in E}(1 / current_rank_j)

CandidateDifference(q)
= sum_{i<j} w_i*w_j*abs(candidate_support(i,q)-candidate_support(j,q))
  / sum_{i<j} w_i*w_j
```

全部可计算 Top-100 candidates 参与，尾部候选权重较低；没有 proxy 的 item 仍留在排名中，但不得用假零分
参加 difference。只有 `CandidateDifference>=0.10` 的 concepts 进入 Need 排序；coverage/mass/floor 不满足时
使用 typed fallback。

### 4.4 Evidence gap and output mapping

若 item `i` 已有成功且 acquisition metadata 引用 concept `q` 的 Deep Evidence，则 `coverage(i,q)=1`，否则为
`0`。成功 Evidence 必须具有合法 observation/ref，并绑定 exact concept ID、query-template version 和 supporting
atom IDs；failed/empty perception 不产生 coverage。在完整 Top-100 上使用前述 `u_i`：

```text
u_i = (1 / current_rank_i) / sum_j(1 / current_rank_j)
EvidenceGap(q) = sum_i u_i * (1 - coverage(i,q))
```

输出映射：

```text
preference_importance = ConceptImportance
contrastiveness       = CandidateDifference
evidence_gap           = EvidenceGap
ranking_relevance      = None
metadata.need_score    = NeedScore
embedding_ref          = selected Chinese-CLIP query vector ref
```

`top1_top2_margin` 只用于 request-level stop/uncertainty，不重复乘入所有 concepts。

P4-03 只发布最多 32 个 aggregate concept diagnostics 和最终 Query 的 per-candidate supports，不发布全量
per-frame/per-segment scores。P4-04 使用 exact selected query embedding 与相同 proxy refs 重算一次该 Query 的
segment relevance；不得换 query/model/template 或重新抽帧。

---

## 5. Implementation Staging

Phase 1 只使用 deterministic `MockInformationNeedEstimator` 验证接口和数据流，
不实现或默认任何真实 Information Need 算法。

Phase 3 负责产生可供本模块消费的真实 `UserMemoryView`，并确认 atom、match、drift、
embedding/matrix refs 的 Information Need readiness；Phase 3 不实现真实 estimator，
也不根据 Memory 单独推断 evidence gap 或 ranking relevance。

Phase 4 P4-03 已确认上述 candidate-aware rule-based baseline。Per-query calibration 和替代 vocabulary/
aggregation/floor 只作为 P6 对照；它们不阻塞第一条真实闭环。
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

## 7. Deferred Research

- P4-04 如何把已选 Query 的 segment relevance 与 rank priority、novelty 和 min value 合成；
- per-query calibration、text-only candidate difference、不同 Top-K、不同 frame aggregation 和 query-free ablation；
- learned/multi-need estimator；
- synonym merge、learned concept vocabulary 和 title-derived needs；
- candidate-difference calibration/threshold 的正式 P6 sensitivity analysis。
