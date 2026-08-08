# Pluggable Initial Ranker and Backbone Experiment Plan

Status: `Provisional experiment companion; P3-03 architecture and first SASRec recipe confirmed`

本文件细化 P3-03 之后如何实现和比较可插拔 Cheap Initial Ranker。它解决四个容易在后期
混淆的问题：哪些内容跨模型共享、SASRec 是否需要训练、BERT4Rec 如何接入，以及论文中
哪些组合需要跑。P3-03 的规范性决定仍以 `phase_3_discussion.md` 为准；最终数据集角色和
完整 method matrix 以 `benchmark_construction_proposal.md` 为准。

---

## 1. Immediate Decision

PAVE-Rec 不是一个写死 SASRec 的系统。SASRec 是第一条默认 Initial Ranker plugin，目的是
尽快完成第一条真实 Agent Loop。系统边界是：

```text
P3-02 immutable derived dataset
        ↓
model-specific training view
        ↓
model-specific model and trainer
        ↓
versioned checkpoint
        ↓
model-specific InitialRanker adapter
        ↓
unchanged AgentController
```

现在只实现 SASRec；完整 Agent Loop 跑通后再实现 BERT4Rec。GRU4Rec 和更强的新模型属于
后期 robustness，不阻塞 Phase 3。

---

## 2. SASRec Must Be Trained

SASRec 不是可以直接拿来对任意数据打分的通用 pretrained model。它的 item embedding 与
训练数据的 item vocabulary 一一对应，因此：

```text
Tsinghua derived dataset
    → train Tsinghua SASRec
    → Tsinghua SASRec checkpoint

MicroLens-100K derived dataset
    → train MicroLens SASRec
    → MicroLens SASRec checkpoint
```

二者共享模型代码、配置 schema、训练算法和评测协议，但不共享 item embedding、vocabulary
或 checkpoint weights。MicroLens-50K 的开发 checkpoint 也不能冒充 MicroLens-100K 的正式
checkpoint。

可以复用的是：

- SASRec 的公开算法、实现思路和已确认超参数 recipe；
- 本项目的模型代码、trainer、collator、evaluator 和 checkpoint loader；
- 一个 dataset checkpoint 继续 resume 同一 dataset、同一 vocabulary、同一 recipe 的训练。

通常不能复用的是：

- 别人在 MovieLens、Amazon 或其他 ID space 上训练的权重；
- Tsinghua checkpoint 直接用于 MicroLens，或反向复用；
- vocabulary/split/positive recipe 不一致的同名数据 checkpoint；
- 仅通过 resize embedding 强行加载的不兼容 checkpoint。

只有 source release、positive/split/view/vocabulary recipe、ID mapping、model config 和 checkpoint
provenance 全部兼容时，现有 checkpoint 才能被视为可复用 artifact。否则必须 fail fast 并重新训练。

SASRec 只使用 item-ID sequence，训练成本通常远低于视频下载、MLLM segment perception 和
Oracle/Segment Value 数据生成；因此第一条 Tsinghua SASRec 训练不应成为完整 Agent Loop 的主要
成本瓶颈。

### 2.1 Required audit before reportable Tsinghua retraining

当前 P3 checkpoint 使用项目自己构建并已做 cutoff/leakage 防护的 chronological leave-two-out split，
可以继续承担 P4 第一条 Agent Loop 的工程输入。清华 processed recommendation package 另带
`x_label=0/1/2` 官方 split；在任何可报告的清华 SASRec 重训或正式 benchmark 前，必须先：

1. 固定 package 和交互文件 checksum、记录 train/validation/test counts；
2. 审计三段 user/item overlap、cold-user/cold-item coverage；
3. 能映射回原始 exposure 时检查每个用户的时间是否满足 train < validation < test；
4. 根据审计结果决定该 split 可否进入 sequential robustness，还是只用于 static MMRec reproduction。

官方论文声明的 8:1:1 本身不能证明 chronological。审计完成前，不得把该 split 直接用于 SASRec
next-item、Dynamic Memory 或 Agent prefix，也不得用它替换当前已版本化的 chronological split。
这项检查同时记录在 `benchmark_construction_proposal.md` 和 `phase_4_discussion.md` P4-00。

---

## 3. Shared Plugin Boundary

### 3.1 Shared Across Rankers

- P3-02 source/split/vocabulary/candidate identities；
- public `InitialRanker.score(user_id, sequence, candidate_ids)` contract；
- exact candidate coverage、stable tie-break 和 fail-fast OOV rules；
- model-independent full-catalog evaluator；
- common metric definitions and warm/cold reporting boundary；
- checkpoint manifest 的共同 provenance 字段；
- Agent、Memory、Perception、Evidence、Score Updater 和 StopPolicy 接口。

Runtime 使用显式、版本化 registry 和 strict discriminated config，例如：

```yaml
initial_ranker:
  type: sasrec
  checkpoint_ref: artifacts/rankers/tsinghua-sasrec-v1
```

后期替换为：

```yaml
initial_ranker:
  type: bert4rec
  checkpoint_ref: artifacts/rankers/tsinghua-bert4rec-v1
```

不接受 arbitrary import string，不根据 checkpoint 文件名猜模型类型，也不在不兼容时降级到
Mock 或另一个 ranker。

### 3.2 Model-specific

- network config and forward pass；
- training-view construction and attention mask；
- loss and training sampler；
- model-only special tokens；
- trainer state and weights；
- raw score scale and model-specific diagnostics。

不建立一个包含所有模型专属字段的巨大通用 Trainer Protocol。共享数据与评测契约，trainer
允许保持 model-specific。

### 3.3 Score Boundary for Later Segment Value

SASRec、BERT4Rec 和 GRU4Rec 的 raw logits 不在同一尺度。后续 Segment Value 不得把 raw score
数值直接解释为跨模型可比的置信度。候选级 cheap features 应优先包含：

- rank and rank percentile；
- request-local normalized score；
- normalized score margin/relative gap；
- candidate-set statistics；
- explicit ranker ID/version。

P3-04 决定 raw score、calibration、StopPolicy 和 checkpoint adapter 的精确语义；P5 决定这些
信号进入 Segment Value feature schema 的最终形式。在完成校准前，不复用 Mock 的 certainty
threshold。

### 3.4 Checkpoint and scoring boundary

P3-04 已确认 checkpoint 使用 exact immutable bundle/manifest ref；`best` 用于 evaluation/Agent，`last`
只用于显式 resume。Runtime 不扫描 `latest`，也不在 checksum、dataset、vocabulary 或 model config
不匹配时 fallback。

Caller 继续显式提供 candidate pool，ranker 精确评分全部 candidates。Candidate OOV fail；history OOV
drop-and-record 后再 recent-50。Public score 是 uncalibrated raw dot-product logit，real-cheap config 的
`ranking_margin_threshold=null`，首版 `user_sequence_feature_ref=null`。完整 bundle 和 score 规范见
`phase_3_discussion.md` P3-04。

---

## 4. First SASRec Recipe

Confirmed recipe ID: `sasrec-pytorch-v1`

| Field | Value |
| --- | --- |
| framework | PyTorch optional training dependency `>=2.8,<3`；运行 manifest 记录精确 Torch/CUDA 版本 |
| input | P3-02 item-ID prefix only；不读取 Memory、metadata、MLLM Evidence 或 segment |
| maximum sequence length | 50；最近事件 left truncation，完整 history artifact 不截断 |
| embeddings | learned item + learned position；PAD=0；input/output item embedding tied |
| hidden size | 64 |
| blocks / heads | 2 / 2 |
| feed-forward size | 256 |
| activation / normalization | GELU；pre-LN + final LN |
| dropout / initialization | 0.2；Normal(0, 0.02)，PAD row 固定为零 |
| primary loss | sampled positive/negative binary loss |
| negative sampler | 每个 positive 一个 uniform train-vocabulary negative |
| optimizer | Adam, lr=1e-3, betas=(0.9, 0.98), eps=1e-8, weight_decay=0 |
| batch / epochs | 128 / at most 200 |
| scheduler | none |
| gradient clipping | global norm 5.0 |
| default precision | FP32；首个基准不开 AMP |
| selection metric | warm-target validation NDCG@10 on P3-02 primary full-catalog protocol |
| early stopping | validate every epoch；patience=10；metric tie 选择更早 epoch |
| checkpoints | `best` 用于评价/推理；`last` 只用于显式 resume |

每个 P3-02 `sample_id` 在一个 epoch 中恰好消费一次，并以该 prefix 的最后一个预测位置计算
目标 loss。Sampler 排除该用户全部 train positives，但不得读取 validation/test positives；其随机数
由 `(training_seed, epoch, sample_id, negative_index)` 确定，使结果不依赖 DataLoader worker
完成顺序。Passive/nonpositive events 不在首版中被暗中转换为训练 negatives。

首个真实运行显式选择 `cuda`；CPU small fixture 和固定 checkpoint CPU inference 必须通过。
Unavailable device 是配置错误，不 silent fallback。首个 Agent Loop 使用一个固定 training seed；论文
最终多 seed 的数量和调参预算由 evaluation Gate 锁定，不以首个 checkpoint 的单 seed 结果代替。

后期增加一次受控 loss sensitivity：

```text
SASRec sampled-BCE
vs
SASRec full-softmax-CE
```

它不阻塞 Phase 3，也不能在未记录 recipe 的情况下悄悄替换主 baseline。

---

## 5. BERT4Rec Plugin Semantics

BERT4Rec 与 SASRec 共享 P3-02 的完整 train histories、split、train-only item vocabulary 和 evaluation
candidates，但不共享 training view：

```text
complete train histories
├── sasrec-next-item-v1
└── bert4rec-cloze-v1
```

BERT4Rec 使用 model-local `[MASK]` ID。该 ID 不加入 rankable item vocabulary，不能出现在 candidates
或推荐结果中。训练只能 mask train history；validation/test target 不得进入 mask construction。Next-item
推理在 cutoff history 末尾追加一个 `[MASK]`，只读取 target 之前的历史，不注入真实 target。

SASRec 和 BERT4Rec 可以使用各自标准 loss 和训练超参数。公平性来自相同数据事件、split、candidate、
metric 和调参预算，而不是强迫不同模型使用完全相同的训练目标。

---

## 6. Experiment Matrix Without Combination Explosion

### 6.1 Ranker-only Quality

在同一数据集内部独立训练、验证和测试：

```text
MostPop
GRU4Rec
SASRec
BERT4Rec
```

固定 split、vocabulary、candidate universe、seen-item mask、metric definitions 和调参预算。报告 ranking
quality，同时报告 parameter count、训练时间、推理 latency 和显存峰值。不同数据集的绝对分数不横比。

### 6.2 PAVE Backbone Robustness

完整 PAVE 主结果只要求先比较两个代表性 backbone：

| Initial Ranker | Cheap Path | Full PAVE | Required comparison |
| --- | --- | --- | --- |
| SASRec | yes | yes | Full PAVE 相对同一 SASRec Cheap Path 的增益 |
| BERT4Rec | yes | yes | Full PAVE 相对同一 BERT4Rec Cheap Path 的增益 |

同时报告 final ranking metric、相对初始 ranker 的 gain、perception calls、cost 和 latency。不要用
`BERT4Rec absolute score - SASRec absolute score` 代替各自的 PAVE 增益。

### 6.3 Full Method Ablations

下列完整消融默认只在 SASRec backbone 上运行：

```text
SASRec
SASRec + Dynamic Memory
SASRec + Random Perception
SASRec + Relevance-only Perception
SASRec + Full Perception
MLLM Reranker with No Evidence
Small latent Reranker capacity comparator
PAVE-Rec
Oracle
```

不要求把全部消融与 BERT4Rec/GRU4Rec 做笛卡尔积。只有当结果显示 PAVE 增益高度依赖 backbone 时，
再由 evaluation Gate 增加针对性消融。

### 6.4 Segment Value Training Under Multiple Rankers

主性能实验中，每个 `dataset × ranker` 独立生成训练轨迹并训练自己的 Segment Value checkpoint，避免
把 SASRec score distribution 强加给 BERT4Rec：

```text
Tsinghua + SASRec       → Segment Value checkpoint A
Tsinghua + BERT4Rec     → Segment Value checkpoint B
MicroLens + SASRec      → Segment Value checkpoint C
MicroLens + BERT4Rec    → Segment Value checkpoint D
```

额外的 portability stress test 可以固定 SASRec 上训练的 Segment Value，零样本切换 BERT4Rec；该结果
回答“是否无需重训即可替换”，不作为每个 backbone 的最佳性能主结果。第一版不要求跨所有 ranker 联合
训练一个统一 Segment Value Model。

### 6.5 Later Cold-Start Evaluation

当前 ID-only SASRec 主线不解决 cold item，但不能隐藏这一缺口：all-target report 统计 target 是否存在于
train vocabulary，cold target 计无法召回；warm-target ranking 单独评价 scorer quality。

Phase 6 可在主 Agent Loop 和两条完整主线之后增加独立 cold-item track：

```text
prediction-cutoff-available item content
  → title/category/video content encoder
  → cold-capable candidate retrieval
  → content-only or SASRec+content hybrid ranking
  → optional PAVE segment perception
```

至少比较：

```text
ID-only SASRec             # 明确的 no-cold-support lower bound
content-only ranker
SASRec + content hybrid
hybrid + PAVE              # 仅当 cold candidates 有可用 segment/media
```

数据协议必须保证 cold item 的 interaction labels 不进入训练；只有 prediction cutoff 前实际可获得的 catalog
metadata/media 可以用于构建 item representation。禁止 target injection、随机 item embedding、统一 UNK
命中或用 test feedback fine-tune 后仍称 zero-shot。

报告：

- cold-target retrieval coverage；
- cold-only Recall/NDCG@K；
- all-target ranking/coverage；
- warm-target quality trade-off；
- content encoding、retrieval 和 perception 的 latency/cost。

优先采用按 item first-availability/first-interaction 的 temporal new-item protocol。若数据不能证明 item 在
cutoff 何时进入 catalog，只能构造 held-out-item generalization，并在论文中使用该名称，不能宣称严格
temporal cold-start。该 track 是后期增强，不阻塞 Tsinghua 第一条完整 Agent Loop。

---

## 7. Delivery Order

```text
1. P3-03: common boundary + sasrec-pytorch-v1
2. Tsinghua single-seed SASRec train/evaluate/checkpoint
3. P3-04/P3-07: load through InitialRanker and run real Cheap Path
4. Complete first Tsinghua Agent Loop
5. Copy pipeline to MicroLens development/main lane
6. Add BERT4Rec plugin
7. Run SASRec/BERT4Rec backbone robustness
8. Add optional GRU4Rec or one stronger later ranker only if the paper claim needs it
```

MicroLens-50K 只验证 pipeline；MicroLens-100K 才是完整第二主线。MicroLens-1M 只做全量 Cheap Path
和抽样 Agent。任何额外 ranker 都不得阻塞第一条 Tsinghua Agent Loop。

---

## 8. Checklist for Future Implementation and Experiments

- [ ] 新 ranker 不修改 `AgentController` 或公共 `InitialRanker` signature。
- [ ] 每个 checkpoint 固定 dataset/split/vocabulary/model/training recipe identity。
- [ ] 清华正式重训前完成官方 `x_label=0/1/2` split provenance、overlap/cold 和逐用户时序审计。
- [ ] 不把其他数据集的 item embedding 当作 pretrained universal weights。
- [ ] BERT4Rec `[MASK]` 是 model-local、non-rankable special ID。
- [ ] 主指标使用相同 full-catalog candidate protocol；dev sampled candidates 不进论文主表。
- [ ] Raw score 不跨 ranker 直接比较或复用 Mock certainty threshold。
- [ ] 完整 method ablation 默认只跑 SASRec。
- [ ] Backbone robustness 至少跑 SASRec 和 BERT4Rec 的 Cheap/Full 配对。
- [ ] Segment Value 最佳性能实验按 dataset/ranker 独立训练；冻结迁移另表报告。
- [ ] 当前 all-target coverage 显式统计 cold miss；不把 warm-only metric 冒充全体性能。
- [ ] 后期 cold-item track 只使用 cutoff 可得内容；temporal 与 held-out-item 命名不混用。
- [ ] 每个结果保存 config、seed、environment、checkpoint 和 evaluator provenance。

---

## 9. Primary References

- SASRec paper and official implementation: <https://github.com/kang205/SASRec>
- BERT4Rec paper: <https://arxiv.org/abs/1904.06690>
- BERT4Rec replicability study: <https://arxiv.org/abs/2207.07483>
- RecBole sequential model interfaces: <https://www.recbole.io/docs/v1.1.1/recbole/recbole.model.sequential_recommender.html>
