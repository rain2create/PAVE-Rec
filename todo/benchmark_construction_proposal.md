# Benchmark Construction Proposal

Status: `Proposal`

Last consolidated: `2026-08-04`

Decision note: 本文件是当前工作建议，不是不可修改的最终实验承诺；任何变更都应在
对应 Phase Gate 记录理由，并同步更新下面的 `Working Invariants`，避免只改局部造成
两套互相冲突的 benchmark 解释。

本文件记录跨 Phase 3—7 的 benchmark 构造建议，避免在讨论第一真实数据集时，
把 sequential ranking、Segment Value、闭环 gain、OPE/RL 和跨域迁移混为一项。

它不是已确认的研究决策，也不替代各 Phase 的 discussion Gate。P3-01 只确认
第一目标数据集及其 source semantics；split、Oracle label、最终 Value Model 和
RL 仍分别由后续 Gate 确认。

---

## 1. Proposed Dataset Roles

| 实验角色 | 数据集 | 边界 |
| --- | --- | --- |
| 核心方法、Dynamic Memory、Segment Value、完整 Agent 主实验 | Tsinghua ShortVideo official public sampled release | 第一条真实端到端主线；使用已审计 sampled 行为/语义元数据和受控 media subset，不要求先下载全部原视频，也不得冒充论文 full 1M release |
| 完整外部 benchmark、SASRec/视频推荐复现、PAVE-Rec 独立复制 | MicroLens-100K | 最终需独立训练和测试完整 Agent；交互语义是 comment engagement，不与 Tsinghua 绝对指标直接比较 |
| MicroLens 管线开发 | MicroLens-50K | adapter、媒体处理和复现 smoke test；不得假设它与 100K 天然构成无泄漏 train/test |
| Cheap Path 规模实验 | MicroLens-1M | 全量 SASRec/Memory/candidate-generation；主动感知只在固定 media/state subset 上运行 |
| 稠密 relevance 与 ranking-side gain 校验 | KuaiRec-small | 校验 gain、Score Updater 和 stop；没有对应原视频，不能证明真实 segment selection |
| 去偏、OPE、可选 offline-RL 辅助 | KuaiRand-Pure | 校验 exposure bias 和策略评价；不是主 Segment Value 数据集 |
| 跨领域泛化 | M³L-10M | 可选且最后进行；movie rating/trailer 语义与短视频行为不同 |

这些数据集不是七条同时推进的主线。最终论文暂定包含两条完整主线，但当前一次只
推进一条实现主线：

P3-01 审计确认：截至 2026-08-04，官方仓库将服务器内容明确称为 `sampled dataset`；当前
`interaction_sampled.csv` 聚合 attribute expansion 后是 129,483 exposures、6,654 users、
31,496 items，而不是论文描述的 1,019,568 interactions。下文的 `Tsinghua ShortVideo` 默认指这份
content-hash-pinned official public sampled release。若作者以后提供 full release，必须作为新 data version
重跑整条 lane，不能原地替换或混表。

```text
Tsinghua ShortVideo
    → real SASRec / Dynamic Memory
    → Deep Segment Encoder + Small Multimodal Reranker loop
    → Tsinghua Oracle data
    → first supervised Segment Value Model
    → stabilize shared implementation
    → repeat the complete protocol on MicroLens-100K
```

MicroLens 是最终必须完成的第二条完整 benchmark lane，但不是当前必须同步实现的
第二套 Agent。先在 Tsinghua 跑通接口和研究闭环，再复用同一实现训练
MicroLens-specific checkpoints。KuaiRec、KuaiRand 和 M³L 只在其能回答的独立
研究问题出现时加入。

### 1.1 Provisional Two-Main-Lane Design

当前临时建议是最终形成两条完整、同构但独立训练的主实验线：

```text
Main Lane A — Tsinghua ShortVideo
    → Tsinghua adapter / split
    → Tsinghua SASRec checkpoint
    → Tsinghua Dynamic Memory
    → Tsinghua Oracle data
    → Tsinghua Segment Value checkpoint
    → Tsinghua full-Agent evaluation

Main Lane B — MicroLens-100K
    → MicroLens adapter / split
    → MicroLens SASRec checkpoint
    → MicroLens Dynamic Memory
    → MicroLens Oracle data
    → MicroLens Segment Value checkpoint
    → MicroLens full-Agent evaluation
```

两条主线共享代码、公共 schemas、算法架构、候选/预算协议、指标和调参预算；分别
拥有 dataset-specific interaction semantics、vocabulary、checkpoint、Oracle labels、
score calibration 和 test artifacts。它们不是两个代码分支，也不是拿 Tsinghua 的
整套 ID-based checkpoint 直接到 MicroLens 测试。

当前实施顺序仍是先完成 Lane A，再复制已稳定的组件实现到 Lane B。该顺序只控制
工程风险，不降低 Lane B 在最终论文中的完整性要求。

### 1.2 Within-Dataset Method Matrix

每条主线内部都需要在同一数据、split、candidate protocol 和 evaluation budget 下
比较多种方法，而不是只训练一个 PAVE-Rec 后报告单点结果。临时方法矩阵为：

```text
SASRec
SASRec + Dynamic Memory
SASRec + Random Perception
SASRec + Relevance-only Perception
SASRec + Full Perception
Small Reranker with No Evidence
PAVE-Rec
Oracle
```

最终主结果表可以采用以下逻辑结构；每个格子都来自该方法在对应数据集上的独立训练
和测试：

| Method | Tsinghua NDCG@10 | MicroLens NDCG@10 |
| --- | ---: | ---: |
| SASRec | TBD | TBD |
| + Dynamic Memory | TBD | TBD |
| Random Perception | TBD | TBD |
| Relevance-only | TBD | TBD |
| Full Perception | TBD | TBD |
| Small Reranker with No Evidence | TBD | TBD |
| PAVE-Rec | TBD | TBD |
| Oracle | TBD | TBD |

实际报告还应包含 perception budget/cost 维度和多个固定 seed 的 `mean ± std`；上表
只表达主比较关系，不提前锁死最终表格布局。

### 1.3 Why Two Complete Datasets and How to Compare Them

只有 Tsinghua 一条完整主线，只能支持：

```text
PAVE-Rec 在 exposure/watch/multi-feedback 任务上有效。
```

增加 MicroLens-100K 完整主线后，可以进一步支持：

```text
PAVE-Rec 在 comment-engagement 任务上也有效，
其收益不只依赖一种行为采集和 relevance 语义。
```

两个数据集任务难度、反馈密度和 ground-truth 定义不同，因此不能用绝对指标做横向
优劣判断：

```text
禁止：Tsinghua NDCG 0.10 > MicroLens NDCG 0.06，
      所以前者模型更好。

正确：Tsinghua 内比较 PAVE-Rec 相对 Tsinghua SASRec 的提升；
      MicroLens 内比较 PAVE-Rec 相对 MicroLens SASRec 的提升。
```

跨数据集可比较的是方法相对各自 baseline 的增益、预算曲线趋势、regret 和成本效率，
而不是未经校准的绝对 score/NDCG。

### 1.4 Supporting Datasets Are Not Additional Full Main Lanes

下列数据集承担受限、可解释的专项角色，当前不要求复制两条主线中的完整训练矩阵：

| 数据集 | 是否完整训练 PAVE-Rec | 具体含义 |
| --- | --- | --- |
| MicroLens-50K | 否，只做开发 | 用于 MicroLens adapter、下载/媒体处理、SASRec/Agent smoke test 和成本估算；不作为 100K 的正式 train/test，也不能假设与 100K 无用户或 item 重叠 |
| MicroLens-1M | 全量 Cheap Path + 抽样 Agent | 全量训练/评价 SASRec、Memory 构建、candidate generation 和吞吐；只对固定 state/media subset 跑 Deep Encoder、Oracle、Segment Value 和 Agent，避免 perception cost 随百万用户全量爆炸 |
| KuaiRec-small | 否，只做 gain/Score Updater calibration | 利用接近 fully observed 的 watch-ratio matrix 检查 before/after ranking gain、Score Updater 和 stop threshold；没有原视频，不能验证真实 segment selection 或 MLLM Evidence |
| KuaiRand-Pure | 否，只做去偏/OPE/可选 RL | 利用随机曝光和 propensity/reward 信息研究 exposure bias、off-policy evaluation 和未来 offline-RL；其 action 是 item exposure/policy，不是视频 segment perception |

这四项都不能替代 Tsinghua 或 MicroLens-100K 完整主线，也不应阻塞第一条 Tsinghua
Agent Loop。是否启用及投入多大资源，由 Phase 5—7 的实际实验威胁和论文主张决定。

### 1.5 Working Invariants — Do Not Forget

除非后续 discussion Gate 明确修改，本 proposal 的工作基线是：

1. 最终必须有 Tsinghua 和 MicroLens-100K 两条完整 PAVE-Rec 主线；
2. 两条主线使用同一实现和评测协议，但独立训练 dataset-specific Initial Ranker、Oracle
   和 Segment Value；SASRec checkpoint 不跨数据集复用；
3. 每条主线内部比较完整 method matrix，不能只报告 PAVE-Rec 单点结果；
4. 跨数据集比较相对各自 baseline 的增益，不比较未经校准的绝对 NDCG；
5. MicroLens-50K 只开发，MicroLens-1M 只做全量 Cheap Path 与抽样 Agent；
6. KuaiRec-small 只校验 ranking-side gain，KuaiRand-Pure 只校验 exposure policy；
7. 先完成 Tsinghua Agent Loop，再复制到 MicroLens；辅助 track 不得阻塞该顺序；
8. 所有 label、candidate、Teacher、Updater、budget 和 cost artifact 必须版本化。

---

## 2. Benchmark Tracks

### Track A — Upstream Reproduction and Data Sanity

目的：证明下载、ID mapping、特征对齐和基础训练环境没有错误。

Tsinghua ShortVideo 可先按照上游 MMRec recipe 复现：

```text
BPR
LightGCN
LayerGCN
VBPR
MMGCN
GRCN
LGMRec
BM3
```

该 track 沿用上游 split 和 feature files，只作数据/环境 sanity check。它不与
PAVE-Rec chronological benchmark 混表，也不宣称评估了主动感知。

正式实验前必须取得并固定上游 processed recommendation package，对交互文件中的
`x_label=0/1/2` 做一次独立的 split-provenance 与时序合法性审计：记录文件 checksum、
三段 counts、user/item overlap、cold-user/cold-item coverage，并在能够映射回原始曝光时检查
每个用户的 train/validation/test 时间是否单调。官方论文只声明 `8:1:1`，因此在完成该审计前，
不得把 upstream split 描述为 chronological，也不得直接用于 SASRec next-item、Dynamic Memory
或 Agent prefix evaluation。若审计证明其 target 前缀严格无未来信息，可另行评估是否复用；若存在
temporal inversion，它仍是合法的 upstream static-MMRec reproduction track，但 PAVE 主线继续使用
独立、带版本的 chronological split。这是后续实验项，不推翻当前 P3 工程 baseline。

MicroLens-100K 另行复现其 IDRec/SASRec 指标，作为 MicroLens adapter 和 Cheap
Path 的 sanity check。

### Track B — PAVE Sequential Ranking and Memory

目的：评价 Cheap Path 和 Dynamic Hybrid Memory，不调用 MLLM。

每个数据集独立执行：

```text
dataset train → dataset-specific checkpoint → same-dataset validation/test
```

共享模型架构、接口、指标和调参预算，但不共享 user/item vocabulary、ID embedding
或未校准 score。

建议基线：

```text
MostPop
GRU4Rec
SASRec
BERT4Rec（第一条 Agent Loop 完成后的第二个 ranker plugin）
SASRec + static/mean memory
SASRec + recent-N memory
SASRec + Dynamic Hybrid Memory
```

可插拔边界、dataset-specific checkpoint、BERT4Rec training-view 差异、完整/受限实验矩阵和
Segment Value 的 per-ranker 训练规则，见
[`initial_ranker_experiment_plan.md`](initial_ranker_experiment_plan.md)。完整 method ablation 默认只在
SASRec backbone 上跑；backbone robustness 先比较 SASRec 和 BERT4Rec 各自的 Cheap Path 与 Full
PAVE，不做全部 ranker × 全部消融的笛卡尔积。

建议指标：

```text
HR@10 / HR@20
NDCG@10 / NDCG@20
MRR@10
Recall@100
```

P3-08 已确认第一条 single-positive protocol：primary 是 full-catalog warm-target `NDCG@10`；
上述指标按 user macro mean 计算，并另外披露 all-target warm/cold retrieval coverage。在每个 case
只有一个 relevant target 时 `Recall@K == HR@K`；保留 `Recall@100` 是为了测量 target 是否进入
后续 Agent 的 ordered Top-100 item pool，而不是因为 primary evaluation 只排 100 个 candidates。
P3-02 的 development-only `1 positive + 100 negatives = 101 candidates` 与该 handoff 无关，不能
进入正式表格。

首条 Tsinghua Agent pipeline 可用 seed `20260804` 快速打通；reportable stochastic ranker result
至少使用固定 seeds `20260804/05/06`，各自 validation-select best 后在 test 报告
`mean ± sample standard deviation`。三 seed 不阻塞第一条 Agent Loop 或 Phase 3 engineering DoD。

Tsinghua 与 MicroLens 的绝对指标不可直接横比。应分别报告相对于同数据集 SASRec
的增益，因为前者包含 exposure/watch/explicit feedback，后者主要是 comment
engagement。

### Track C — Segment Value and Active Agent

目的：评价哪个未感知 segment 在当前 Recommendation State 下具有最高推荐增益。

Track C 最终在 Tsinghua 和 MicroLens-100K 两条主线各构建一次，并分别训练
dataset-specific Segment Value。第一轮只在 Tsinghua ShortVideo 上构建；不要为了
“多数据集”在第一轮同步生成两套昂贵 Oracle 数据。Tsinghua 可优先使用下面的
observed-candidate benchmark；MicroLens 因缺少同等曝光/观看反馈，主要使用
open-world/target-injected comment-engagement protocol，并单独披露 implicit-negative
局限。

#### C1. Observed-Candidate Benchmark

在用户时间线的 cutoff 之前构建 history、Memory 和 SASRec state；从 cutoff 之后的
实际 exposure 中构建固定 candidate pool。候选已经具有 watch time、effective view、
explicit engagement 或 hate 等观测反馈，适合生成较可信的 graded relevance。

该候选集合是 offline `future observed candidate set`，不是平台同时展示的真实 slate；
报告和论文必须保留这个限定。

建议的 relevance vocabulary（待数据审计和后续 Gate 确认）：

```text
0: hate，或没有形成有效观看
1: effective view
2: high completion/watch ratio
3: like/comment/follow/collect/forward
```

`effective_view == false` 在该评价 vocabulary 中可以为 0，但不得被描述为用户明确
负反馈；明确负反馈只有 `hate`。

#### C2. Open-World Retrieval/Reranking Benchmark

```text
SASRec full-catalog top-100
    → report Recall@100
    → select hard candidate pool
    → explicitly inject held-out positive when required
    → report conditional reranking metric separately
```

强制加入 target 的结果只证明 conditional reranking，不得替代 candidate retrieval
结果。这里的 Top-100 是 item-level Agent/reranking pool；P4-02 已确认对其中全部 media/proxy-eligible segments 批量计算 cheap value，但昂贵路径每轮只深度编码全局 argmax 的一个 segment，不能解释成默认感知 100 个视频的全部 segments。P3 full-catalog Top-100 不注入 target；只有单独命名的 conditional reranking
benchmark 才能注入并同时保留原始 Recall@100 ceiling。

#### C3. Segment and Oracle Label

P4-01 已确认第一条 Tsinghua 主 segmentation 使用 `scene-hybrid-v1`：pinned shot-boundary
detector 先产生 raw shots，再以 semantic similarity、boundary confidence 和 duration rules
合并/切分，形成数量可变但有上限的 perception segments。Official-100 audit 从 1.5—8 秒、
每 item 最多 12 段开始；任何调整必须产生新 recipe/version。固定 `K = 8` 等时长 segment
保留为 segmentation ablation，并可在需要跨数据集严格控制 segment 数时单独报告，不能与
scene-based 主结果混用。Tsinghua 上游八段视觉特征只作独立 proxy/provenance 候选；真实
Perceiver 所需媒体仍通过显式 media/segment refs 管理。

对每个 sampled state 和未感知 segment：

```text
before ranking
    → fixed Deep Segment Encoder / Evidence lookup
    → frozen Small Candidate-aware Multimodal Reranker
    → after ranking
    → gain = metric(after) - metric(before)
```

第一条建议 label：

```text
primary:   delta NDCG@10
secondary: delta MRR, delta target rank, top-1 flip, regret reduction
```

负 gain 必须保留。Oracle artifact 必须记录 state、segment、encoder/preprocess、Evidence、
Small Reranker、before/after ranking、raw gain、cost 和 label 版本。

Supervised Segment Value Model 只能读取 online 可用的 cheap features，不能读取
Teacher Evidence、after ranking、future feedback 或 actual gain。

#### C4. Split and Evaluation

至少需要：

```text
user-disjoint value-model test
cold-item/cold-segment test
```

建议 offline 指标：

```text
Spearman(predicted gain, actual gain)
pairwise segment-selection accuracy
top-1 oracle-hit rate
regret vs oracle
```

建议 end-to-end 指标：

```text
NDCG@10 at perception budget 0 / 1 / 2 / 4 / 8
area under the budget curve
gain per perception action
token / frame / latency cost
```

建议策略基线：

```text
No perception
Random
Uniform
Top-ranked item first
Query-segment similarity
Uncertainty-only
Relevance-only
Supervised Segment Value
Full perception
Oracle
```

### Track D — MicroLens Benchmark Ladder

MicroLens 相关的三个规模必须保持不同职责，不能混成自然的 train/test 层级：

#### D1. MicroLens-50K — Development Only

用于 MicroLens adapter、下载和媒体处理、SASRec/Agent smoke test、资源需求与 Deep Encoder/MLLM
成本估算。它不进入正式主结果表，也不作为 100K 的训练集。除非通过 source audit
明确证明，否则不能假设 50K 与 100K 用户或 item 无重叠。

#### D2. MicroLens-100K — Complete Second Main Lane

在 MicroLens-100K 上独立训练 MicroLens-specific SASRec、Memory、Oracle 和
Segment Value checkpoint，并运行与 Tsinghua 相同的 method matrix、budget curve 和
Agent ablation。该任务的 relevance 是 comment engagement，结果必须按此命名和解释。

实施可分阶段，但最终完整复制是必做项：

```text
D2a: MicroLens SASRec/VideoRec reproduction
D2b: heuristic active-perception baseline
D2c: MicroLens Oracle + supervised Segment Value + full Agent
```

#### D3. MicroLens-1M — Full Cheap Path, Sampled Agent

全量运行数据预处理、SASRec、Memory、candidate generation 和吞吐/存储评测；Deep Encoder/MLLM、
Oracle、Segment Value 与完整 Agent 只在固定、版本化的 state/media subset 上运行。

原因是 perception 计算量近似：

```text
number of states × candidate items × segments × Deep-Encoder/Teacher cost
```

因此 1M track 分别报告全量 Cheap Path 的质量/规模结果和 sampled Agent 的预算曲线，
不把它描述为第三条百万用户全量感知主线。

### Track E — Dense Gain Calibration with KuaiRec-small

KuaiRec-small 用接近 fully observed 的 user-item watch-ratio matrix 校验 ranking-side
逻辑：

```text
before ranking
→ simulated/fixed score update
→ after ranking
→ dense-relevance gain
→ stop/calibration analysis
```

它可以回答：

- gain formula 是否稳定；
- Score Updater 是否真的改善已观测 relevance；
- stop threshold 是否校准；
- implicit-negative noise 对结果有多大影响。

它不能回答：

- 是否选择了正确的真实视频 segment；
- MLLM Evidence 是否正确；
- Segment Value Model 是否理解了视频。

因此它是独立 calibration track，不训练或替代完整 PAVE-Rec，也不纳入第一条 Agent
Loop 的运行依赖。

### Track F — Exposure Bias, OPE, and Optional RL with KuaiRand-Pure

KuaiRand-Pure 的随机曝光日志用于：

```text
IPS/SNIPS-style correction
off-policy evaluation
exposure-bias sensitivity
optional offline policy/RL extension
```

它评价的是 item exposure/reward policy，不是原视频 segment perception policy；其
action space 与 PAVE-Rec 的 `(item, segment)` perception action 不同。只有 Phase 6
结果显示 exposure bias 是主要结论威胁，或 Phase 7 明确进入 OPE/RL 研究时才实现。

### Track G — Optional Transfer and Cross-Domain Evaluation

Tsinghua → MicroLens transfer 是独立附加实验，不替代 D2 的 MicroLens from-scratch
完整主线。可选比较：

```text
MicroLens from scratch
Tsinghua-trained semantic/value modules zero-shot
Tsinghua checkpoint fine-tuned on MicroLens
```

SASRec ID embeddings、item/user vocabulary 和 score calibration 不能零样本复用。
可迁移对象限于具有共同 canonical feature space 的 content encoder、Memory 机制、
Value architecture/weights、Perceiver prompt 和 Evidence schema。

M³L-10M 只在需要 movie/trailer 跨领域结论时追加。其 rating 与 trailer 语义不等同于
短视频观看反馈，结果必须单独解释，并放在两条完整短视频主线之后。

### Track H — Optional Cold-Item Evaluation

当前纯 ID SASRec 主线只报告 cold-target coverage/miss 和 warm-target conditional ranking，不声称已经
解决 cold start。Phase 6 主结果完成后，可增加独立 cold-item recovery：

```text
ID-only SASRec
content-only ranker
SASRec + content hybrid
optional hybrid + PAVE
```

Cold item 的 interaction labels 不得进入训练；candidate representation 只能使用 prediction cutoff 前可得的
title/category/video/catalog 信息。Candidate pool 必须允许真正 unseen items 被 content path 召回，禁止
target injection、random/UNK embedding 或查看 test feedback。

报告 cold-target retrieval coverage、cold-only Recall/NDCG@K、all-target coverage/ranking、warm quality
trade-off 和额外 compute/perception cost。优先使用 item first-availability/first-interaction 的 temporal
new-item split；若 dataset 没有可靠 catalog availability 时间，只能报告 held-out-item generalization，
不得写成严格 temporal cold-start。该 Track 不替代 Tsinghua/MicroLens-100K from-scratch 主线，也不阻塞
第一条 Agent Loop。

---

## 3. Minimal Delivery Order

为了尽快获得第一条真实完整 Agent Loop：

```text
P3: Tsinghua sampled adapter + derived sequence + SASRec + Dynamic Memory
P4: official 1..100 media smoke → coverage-driven Tsinghua media subset
    → frozen Deep Encoder + heuristic Segment Value + Small Reranker
P5: Tsinghua Oracle data + first supervised Segment Value Model
P6: Tsinghua main evaluation + KuaiRec calibration + complete MicroLens PAVE-Rec replication
    → MLLM-text + LLM Reranker system-level comparison
    → optional cold-item evaluation after main results
P7: optional KuaiRand OPE/RL and M³L transfer
```

KuaiRec calibration 也可在 Phase 5 提前运行，但不应阻塞 Tsinghua Agent Loop。

---

## 4. P3-01 Boundary

本 proposal 不要求 P3-01 同时确认全部数据集。建议 P3-01 只确认：

```text
first target dataset: Tsinghua ShortVideo official public sampled release
first implementation scope: content-hash-pinned sampled behavior/semantic metadata
                            + controlled media subset
```

P3-01 需要固化的仍然是：snapshot/version、许可、下载/缓存边界、ID 与 interaction
semantics、item field inventory、missing-data policy 和 P2 ingestion boundary。

MicroLens、KuaiRec、KuaiRand、M³L 的 adapter 和 dataset-specific semantics 在相应
benchmark 真正排期前分别确认，不扩大第一条实现主线。

---

## 5. Required Reproducibility Artifacts

每条实际启用的 track 都必须保存：

```text
source snapshot and checksums
adapter/split/candidate recipe versions
user/item vocabulary refs
feature encoder versions
model/checkpoint IDs
Deep Encoder/preprocess and optional Teacher/MLLM/prompt versions
Small Reranker and gain-label versions
seeds
ranking and perception-cost metrics
agent traces
```

真实数据、媒体、下载缓存、派生数据、Oracle Evidence 和 checkpoints 默认不进入 Git；
仓库只保存 schemas、configs、manifests、checksums、processing code 和小型合成 fixture。
