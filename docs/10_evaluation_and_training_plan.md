# Module 10 — Training and Evaluation Plan
# 训练与评估方案

## 1. 核心目标 Goal

不仅评估 recommendation accuracy，还要评估：

```text
每花一次昂贵 multimodal perception，
到底带来了多少 recommendation quality gain？
```

---

## 2. Training Stages

### Stage 1 — Preprocessing

构建：

- user sequences
- item features
- video segments
- segment proxies

### Stage 2 — Train SASRec

得到 conventional sequential recommendation prior。

### Stage 3 — Build Dynamic User Memory

完成：

```text
long-term atoms
short-term atoms
similarity matrix
stable / emerging / fading update
```

第一阶段可以先 offline 或 simulated。

### Stage 4 — Build Native-frame MLLM Reranker Data and Runtime

建立第一条真实正预算主线所需的基础数据与接口：

- Rule-based Information Need 与 Query-relevance Segment Value bootstrap
- selected raw-frame `SegmentPerceiver` bundle/refs
- balanced split-safe Observation State dataset
- Top-100 compact candidate serialization 与 acquisition Query/Memory context
- `Qwen3-VL-8B-Instruct` packed `ScoreUpdater` adapter、100 candidate-token logits 和 score artifacts
- No-Evidence、target/non-target、multi-item/segment、mismatch/shuffle/mask/permutation states
- score/stop compatibility and Selector/MLLM perception-cost artifacts

### Stage 5 — Train and Freeze Native-frame MLLM Reranker

- 锁定 `Qwen3-VL-8B-Instruct` exact revision/processor/license，并定义 100 个专用 candidate tokens；
- 从原始 Qwen checkpoint 做 full-parameter recommendation ranking training；ZipRerank checkpoint warm-start、
  LoRA/QLoRA 和 vision-freeze 只作消融；
- 一次 packed forward 后在 final scoring position gather 100 candidate-token logits，不生成 ranking 文本/score JSON；
- primary listwise next-item loss + no-evidence prior consistency + mask/mismatch objectives；
- 在 validation 上确认相对 SASRec、No-Evidence、pointwise `Qwen3-VL-Reranker-8B` 和 Small-latent comparators
  的有效稳定提升；
- 冻结 exact Reranker checkpoint，作为后续 Selector utility teacher。

### Stage 6 — Build Counterfactual Segment-Selector Data

对 sampled recommendation state 和 stratified segment subset：

- 使用 canonical selected raw-frame Evidence；
- 从固定 SASRec base + 完整 EvidenceState 重算 before/after ranking；
- 使用冻结的 exact MLLM Reranker 保存 `Δ log p(target)`、cost 与辅助 rank metrics；
- 分层覆盖 item rank、target/non-target、Query relation、duration/content diversity、random/hard negatives；
- 不要求每个 state 穷举全部约 1200 segments，但必须记录 label coverage 和 sampling probability。

### Stage 7 — Train ≤1B Multimodal Segment Selector

```text
all eligible segment low-resolution multi-frame compact tokens
+ state + information need + Memory + SASRec rank/score
→ query-conditioned local compression
→ global segment scalar values
→ expected recommendation gain
```

Proposed Selector 不使用独立 CLIP shortlist；全部 eligible segments 必须得到输出。先冻结 vision tower 使用
versioned content-token cache 训练 fusion/head，再选择性解冻后层并重建 final cache。

### Stage 8 — Integrate End-to-End Agent

运行完整 active-perception loop。

### Stage 9 — Optional Alternating/Joint/RL Research

第一条 baseline 不联合训练。只有 frozen-Reranker → Selector 的 supervised system 稳定后，才比较 label refresh、
alternating tuning、distillation、soft selection、bandit/RL 或其他 joint approaches。

---

## 3. Recommendation Metrics

Phase 3 single-positive next-item protocol 固定为 full-catalog warm-target ranking。若 target 的
1-based rank 为 `r`：

```text
HR@K     = 1[r <= K]
NDCG@K   = 1[r <= K] / log2(r + 1)
MRR@10   = 1[r <= 10] / r
Recall@K = HR@K                 # one relevant target per case
```

Primary metric 是 `NDCG@10`；secondary metrics 是 `HR@10`、`NDCG@20`、
`HR@20`、`MRR@10` 和 `Recall@100`，按 user macro mean 聚合。Warm targets 使用完整
train vocabulary、seen-positive filtering 和 repeated-target exception；cold targets 不注入
scorer，单独进入 all-target retrieval coverage/counts。

由于任务是 single-target next-item，Agent 的 stop/value 决策采用 Top-1-centric protocol，并把 `HR@1 / Top-1 Accuracy`、Top-1/Top-2 normalized margin 和目标 item log-probability 作为关键 Agent 指标；标准推荐主表仍保留 NDCG@10 等 listwise 指标。raw SASRec/reranker logits 未校准，margin threshold 只能在 validation 上确定。

```text
full catalog
    → Initial Ranker
    → ordered Top-100 items
    → later Agent candidate pool
    → cheap value over all media/proxy-eligible segments
    → deep encode one selected segment
    → rerank Top-100 and output Top-1
```

`Recall@100` 衡量 target 是否进入后续 Agent pool，不表示深度编码或 MLLM 对比支线感知全部 100 个 items。
Development-only `1 positive + 100 negatives = 101 candidates` 只用于 smoke/CI，不是该
Top-100 handoff，也不进入 research table。MostPop 与 SASRec 是 Phase 3 minimum real-data
comparators；第一条真实 pipeline 使用 seed `20260804`，正式 stochastic result 至少使用
`20260804/05/06` 三 seed 报告 `mean ± sample standard deviation`。

---

## 4. Perception Efficiency Metrics

重点评估：

```text
ranking quality vs number of perceived segments
ranking quality vs deep encoder FLOPs / MLLM token cost
ranking quality vs frames processed
ranking quality vs latency
```

例如：

```text
NDCG@10 after 0 perception steps
NDCG@10 after 1 perception step
NDCG@10 after 2 perception steps
...
```

另外可以记录：

```text
Gain per Perception Action
```

---

## 5. Segment Selection Evaluation

需要和以下方法比较：

```text
Random segment
Uniform segment
Top query-segment similarity
Top item first
Uncertainty-only heuristic
P4 Chinese-CLIP Query-relevance bootstrap
CLIP-shortlist + learned Selector comparator
Proposed ≤1B Multimodal Segment Selector（all eligible, no external shortlist）
Oracle segment selection
```

`All-Segment` 只能作为 full-information reference，不保证是上界；同预算枚举得到的 Oracle Segment 才是 selection upper bound。必须同时报告 conditional reranking（target 已被召回）和 end-to-end retrieval + reranking；validation/test 不做 target injection。

这一组对比用于证明：

```text
Recommendation-aware Expected Value
```

比普通 generic relevance 更适合当前问题。

---

## 6. Agent Ablations

可以考虑：

```text
w/o Dynamic Memory
w/o Information Need
w/o Multimodal Segment Selector
w/o Active Stop
w/o Evidence Update
MLLM Reranker with No Evidence
Small latent Reranker capacity comparator
text-only MLLM Reranker
fixed-frame perception
full-video perception
```

### 6.1 Query-generation and frame-extraction ablations

P4 的 Memory、candidate-aware Query、Chinese-CLIP bootstrap proxy 和 selected-frame recipe 只定义第一条
可复现 pipeline baseline。P6 将 proposed Selector 与 MLLM Reranker 的 frame/token choices 拆成独立实验轴：

```text
Query-generation / Memory axis
- short recent window
- long recency half-life
- max active atoms and inactive threshold
- persistence/importance/state-transition recipes
- concept vocabulary, IDF/cap, template, encoder and calibration

Selector visual-compression axis
- low-resolution source decode and frame count (3/6/8/12/16)
- uniform / medoid / scene-aware positions and invalid-frame replacement
- Selector-owned vision tower/tokenizer and freeze/unfreeze recipe
- compact tokens per frame/segment、query-conditioned resampler and cache identity
- Selector size (100M/300M/500M/1B)、within-item segment context and cross-item global scorer
- proposed all-eligible path vs CLIP-shortlist comparator
- hierarchical cross-video Selector vs adapted single-video keyframe/clip selector baseline

MLLM Reranker frame/context axis
- selected raw-frame count (4/8/16/32), resolution and native image/video API
- multiple observed-segment packing and Top-100 candidate context budget
- 100 candidate-token schema、candidate shuffle、single-token logits vs pointwise/chunked scoring
- 3B/8B/larger scale、full-tune vs LoRA/QLoRA/vision freeze、ZipRerank checkpoint warm-start
- SASRec residual calibration、QI-EI optional pruning and text-only/Small-latent comparators
```

Selector 不得把最多数千 raw images 拼进一个全局语言上下文；先在 segment 内编码/压缩，再只让 global scorer
处理约 1200 个 segment-level tokens。低清 source decode、frame count、compact-token count 和 model FLOPs 必须
联合报告。Selector frame/token 实验与 8B MLLM selected-frame/context 实验分开进行，避免把“是否选对 segment”
和“选中后 Reranker 看了多少内容”的收益混在一起。

正式协议先固定 frame side 比较 Memory/Query variants，再固定 Memory side 比较 frame variants，最后才组合各自
最佳候选。每个 variant 使用独立 config、recipe/version 和 artifact identity，并在既定 user/time split 后
重建兼容的 Memory、Query、Selector-token、raw-frame Evidence 和 Reranker artifacts。报告 Query fallback/
candidate-difference/gap/stability、segment-selection 分布、Selector/MLLM frames/tokens/FLOPs、ranking gain、
latency、peak memory 和存储成本，不能只看最终 NDCG。

---

## 7. Memory Evaluation

Phase 3 使用 exact synthetic golden transitions 验证：

```text
stable reinforcement
unseen short → emerging
repeated emerging → promotion
fading / inactive / reactivation
empty long/short and drift boundaries
same-time / repeat / idempotency
cutoff leakage prevention
persistence/reload and public-view ref integrity
```

真实 Tsinghua snapshot build 只报告 aggregate diagnostics：semantic/Memory coverage、
long-empty、stable/emerging/fading、promotion/inactive、atom counts、cosine 和 drift
distributions。当前没有人工 Memory-state ground truth，因此这些 audit 不设效果通过阈值，也不能
用 fixture pass 宣称 Memory 已提高 recommendation quality。

在 `perception budget=0` 时没有 active-path component 消费 Memory；同 checkpoint/candidates
下，加载 Dynamic Memory 前后的 SASRec ranks 必须一致。Memory 的 next-item gain、interest
classification agreement、emerging/fading detection 和 profile freshness benchmark 留到 Phase 6。

---

## 8. Value Model Evaluation

Offline：

```text
correlation(predicted_gain, actual_gain)
pairwise segment-selection accuracy
top-1 oracle-hit rate
regret vs oracle
```

End-to-end：

```text
final NDCG under the same perception budget
```

---

## 9. Budget Curves

必须评估：

```text
x-axis: perception budget
y-axis: recommendation metric
```

这会是整篇论文里非常重要的结果展示方式之一。

---

## 10. Required Experiment Logging

每个实验保存：

```text
exact config and seed(s)
dataset/split/subset refs
model/checkpoint/memory identities
candidate/filter/metric recipes
warm/cold counts and ranking metrics
per-target rank/miss and ordered Top-100 outcome
budget and perception-cost metrics
agent/evaluation artifact refs
environment and code provenance
```

Phase 3 每个 checkpoint/baseline evaluation 发布独立 immutable artifact：

```text
evaluation_manifest.json
aggregate_metrics.json
per_target_outcomes.jsonl
```

它不保存 full-catalog score matrix，不把 target label 暴露为 online feature，也不改变 Agent
run 只能包含 `resolved_config.json`、`trace.jsonl` 和 `result.json` 的约定。

### 10.1 First exact Tsinghua test results (2026-08-04)

以下是 Phase 3 engineering acceptance 的单 seed 真实结果，不是三 seed paper table，也不用于证明
SASRec 必须超过 MostPop。两者使用同一 P3-02 test subset、train-only vocabulary、seen-positive mask
和 v2 batched full-catalog evaluator；all/warm/cold target 数分别为 `4298/3692/606`，all-target
retrieval coverage 为 `0.8590041880`。

| Method | NDCG@10 | HR@10 | NDCG@20 | HR@20 | MRR@10 | Recall@100 |
|---|---:|---:|---:|---:|---:|---:|
| MostPop | 0.001939 | 0.005146 | 0.003578 | 0.011647 | 0.001028 | 0.054713 |
| SASRec (seed 20260804) | 0.006081 | 0.013814 | 0.008233 | 0.022481 | 0.003784 | 0.072589 |

精确 evaluation refs：

- MostPop: `p3eval-efbbf0f3d92ebc8d1bb4d2833c52ffe8b36ee513fc95bd7019e832cd126af026`
  (`sha256:de7ac9bd409dc167301d7e9438eb99213ee313b857d0aa043acfce7caed2d726`)
- SASRec: `p3eval-a4b12056384ffb424d2f4ecb7c7a0d4eba7a3071379bab988850e50b3fa7f335`
  (`sha256:fcd6a7d91ab4780ab7922cdcd0d4f810280b53b85c15a52fe2716318be6bca58`)

Execution identity 显式记录 evaluator version、device、candidate chunk size 和 user batch size；不同
batch recipe 的 artifact 不会静默复用为同一结果。

---

## 11. Phase 3 Acceptance Boundary

Phase 3 engineering completion 需要 single-seed exact Tsinghua derive/semantics/SASRec/Memory/
evaluation lifecycle、MostPop comparator、zero-budget real Agent run/replay、package branch coverage
至少 90%、Ruff、既有三平台 core CI 和一个 required Ubuntu Python 3.12 CPU-PyTorch job。

Phase 3 completion 不要求 SASRec 超过 MostPop，也不要求三 seed paper table、真实 Information
Need、Segment Value、MLLM、MicroLens、BERT4Rec 或 cold-start recovery。真实 dataset/model/GPU
不进入普通 CI；tests offline/CPU-only，只写 pytest temporary roots。

---

## 12. TBD

- exact ground-truth definition
- exact value-model label
- exact oracle construction
- final baselines
- whether to include RL
