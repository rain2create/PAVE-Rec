# Module 02 — SASRec Cheap Initial Ranking
# SASRec 低成本初始排序模块

## 1. 模块目标 Purpose

在不进行昂贵视频多模态理解的前提下，先得到一个 initial candidate ranking。

这个模块提供一个 conventional recommender prior，作为后续 Agent 主动感知的起点。

第一条真实 Cheap Path（路线图 Phase 3）默认：

```text
SASRec
```

SASRec 是第一个 `InitialRanker` plugin，不是系统写死的唯一模型。模型专属训练与 checkpoint
可以替换，Agent Controller 只依赖公共 `InitialRanker` contract。

后续可以替换或增加 baseline：

- GRU4Rec
- BERT4Rec
- Two-Tower
- LightGCN
- production recommender

---

## 2. 输入 Input

```python
user_interaction_sequence: list[item_id]
candidate_ids: list[item_id]
```

Phase 3 的第一版先以标准 sequential recommendation 为主。

---

## 3. 输出 Output

跨模块输出使用
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md) 中的公共 Schema：

```python
class InitialRankedCandidate:
    item_id: str
    score: float
    rank: int


class InitialRankingOutput:
    candidates: tuple[InitialRankedCandidate, ...]
    user_sequence_feature_ref: ResourceRef | None
    metadata: JsonObject
```

SASRec 内部可以使用 Tensor，但跨模块输出只暴露显式 candidate entries 和
可选 feature reference，避免 `scores` 与独立 `ranking` 发生不一致。

例如：

```text
A 0.81
B 0.79
C 0.63
D 0.42
```

---

## 4. 与 Dynamic User Memory 的职责区分

Dynamic Hybrid User Memory 负责：

```text
用户当前在意什么？
兴趣怎么变化？
哪些兴趣正在 emerging / fading？
```

SASRec 负责：

```text
给定用户历史行为序列，
当前 candidates 应该怎么排？
```

第一条真实实现仍保持两者分离。

不要一开始就把 `PreferenceAtom` 直接融合进 SASRec。

两部分最终在 `Recommendation State` 层汇合。

---

## 5. Basic Model

```text
item sequence
    ↓
item embedding
    +
position embedding
    ↓
masked self-attention blocks
    ↓
user sequential representation h_u
    ↓
candidate item embedding dot product
    ↓
candidate score
```

Conceptual score：

```text
score(u, i) = h_u · e_i
```

---

## 6. Training Data

使用标准 sequential next-item prediction。

对每一个 user sequence：

```text
[i1, i2, i3, ..., it]
```

构建 prefix / target training pairs。

P3-03 第一条 `sasrec-pytorch-v1` 使用 sampled positive/negative binary loss；每个 positive
从 train vocabulary 均匀采样一个 negative，并排除该用户的 train positives。Sampler 不读取
validation/test positives，recipe 和 seed 必须进入 checkpoint provenance。Full-softmax CE 只作为
后续显式 loss-sensitivity 实验，不能静默替换首版 recipe。

### 6.1 Training and checkpoint reuse

SASRec 必须在目标数据集上训练。Item embedding 与该数据集的 train-only vocabulary 一一对应，
所以 Tsinghua 和 MicroLens-100K 分别产生自己的 vocabulary 和 checkpoint：

```text
Tsinghua → Tsinghua SASRec checkpoint
MicroLens-100K → MicroLens SASRec checkpoint
```

可以跨数据集复用模型代码、配置 schema、训练算法和评测协议，不能直接复用 ID embedding 或
checkpoint weights。只有 source release、positive/split/view/vocabulary recipe、ID mapping 和 model
config 全部兼容时，已有 checkpoint 才可以 resume 或加载；否则必须 fail fast 并重新训练。

### 6.2 Warm/cold and OOV boundary

Candidate 必须存在于 checkpoint 的 exact train vocabulary；candidate OOV、PAD 或 model-only special ID
直接失败，不分配随机 embedding、不映射 UNK、不返回伪零分。Evaluation 在调用 scorer 前识别 cold
target：all-target retrieval coverage 将其计为 miss，warm-target ranking 只评价真正可打分的 targets。

History 中的 OOV event 记录后丢弃，再从 known events 中取最近 50 个；repeated known events 保留。若
没有任何 known history，则显式失败，cold-user fallback 留给 P3-06。当前做法测量但不解决 cold-item
缺口；后期 content-only/hybrid/PAVE cold-item protocol 见
[`../todo/initial_ranker_experiment_plan.md`](../todo/initial_ranker_experiment_plan.md)。

真实 P3 `AgentRunRequest.user_history` 固定为 target/full-exposure cutoff 前完整、未截断的
`positive_v1` item-ID projection。它是 SASRec 与 Memory 共用的 P1-compatible tuple，不包含 passive/
negative type，也不承担选择 Memory snapshot 的职责；exact cutoff/snapshot 已由 bootstrap 绑定。SASRec
在内部先做 OOV drop-and-record，再 recent-50。不得把 recent-50 结果回写公共 request，Memory 也不得仅凭
相同 tuple 猜测 full-exposure cutoff。

### 6.3 Evaluation and Top-100 handoff

Primary evaluation 在完整 train vocabulary 上进行；`NDCG@10` 是 checkpoint-selection/primary
metric，另报 `HR@10`、`NDCG@20`、`HR@20`、`MRR@10`、`Recall@100` 和 all-target
cold/warm coverage。每个 case 只有一个 relevant target，因此 `Recall@K == HR@K`；保留
`Recall@100` 是为了测量 full-catalog target 能否进入下游 Agent 的 ordered Top-100 item pool。

```text
full train vocabulary → SASRec ranking → Top-100 Agent candidates
                                      → later smaller Top-L expensive search
```

这不要求后续 MLLM 感知全部 100 个 items；Phase 4/5 再确认进入 Segment Value/Perception 的
item/segment shortlist。P3-02 development-only 的 `1 positive + 100 negatives = 101 candidates`
只用于 smoke/CI，不是 full-catalog Top-100 handoff，不得进入正式结果。

Phase 3 minimum comparator 是 train-only MostPop。第一条真实 Agent pipeline 使用 seed
`20260804`；可报告的 stochastic ranker result 至少使用固定 seeds `20260804/05/06`，每个
seed 独立 validation-select best，并在 test 上报告 `mean ± sample standard deviation`。三 seed
结果不阻塞第一条 Agent Loop 或 Phase 3 engineering completion。

---

## 7. Required APIs

权威接口见
[`00_component_interfaces.md`](00_component_interfaces.md)：

```python
class InitialRanker(Protocol):
    def score(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
    ) -> InitialRankingOutput:
        ...
```

Implementations：

```text
SASRecRanker
BERT4RecRanker (later plugin)
GRU4RecRanker (optional later plugin)
MockRanker
```

---

## 8. Engineering Requirement

不要让 Agent Controller 依赖 SASRec 内部实现细节。

Agent 只消费：

```text
candidate_id
score
ranking
optional hidden-state / sequence-feature reference
```

不同 ranker 的 raw score 不可直接横向解释为相同置信度。P3-04 负责 score/calibration/StopPolicy
精确语义；在校准完成前不能复用 Mock certainty threshold。后续 Segment Value 应优先使用 rank、
percentile 和 request-local normalized signals，并记录 ranker ID/version。

---

## 9. First Real Implementation Goal (Phase 3)

支持：

```bash
python -m pave_rec.cli.phase3 train-ranker --config configs/phase3/sasrec_train.yaml
python -m pave_rec.cli.phase3 evaluate     --config configs/phase3/evaluate_sasrec_test.yaml
python -m pave_rec.cli.phase3 run          --config configs/phase3/runtime_zero_budget.yaml
```

Phase 3 通过真实 Memory、SASRec 和 persistent Stores 在不修改 Controller 的情况下完成
zero-budget Cheap Path。Phase 1 all-Mock runner/config/goldens 保持原样；Phase 3 offline
train/evaluate 与 online run 是不同 lifecycle，不在 Agent 启动时训练模型。

详细的 ranker 插件边界、BERT4Rec training view、实验矩阵和 Segment Value compatibility 见
[`../todo/initial_ranker_experiment_plan.md`](../todo/initial_ranker_experiment_plan.md)。

---

## 10. TBD

- candidate-generation source
- whether multimodal cheap features enter the initial ranker
- whether user memory is fused into SASRec in later experiments
- final equal hyperparameter-search budget across later ranker plugins
