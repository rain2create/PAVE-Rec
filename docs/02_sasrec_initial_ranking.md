# Module 02 — SASRec Cheap Initial Ranking
# SASRec 低成本初始排序模块

## 1. 模块目标 Purpose

在不进行昂贵视频多模态理解的前提下，先得到一个 initial candidate ranking。

这个模块提供一个 conventional recommender prior，作为后续 Agent 主动感知的起点。

第一条真实 Cheap Path（路线图 Phase 3）默认：

```text
SASRec
```

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

Negative sampling 的具体策略保留 configurable。

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

---

## 9. First Real Implementation Goal (Phase 3)

支持：

```bash
python scripts/train_sasrec.py
python -m pave_rec.cli.run_mock --config configs/mock.yaml
```

进入 Phase 3 后，Mock agent harness 可以在不修改 Controller 的情况下消费真实
SASRec score。Phase 1 本身仍只实现 MockInitialRanker，不训练真实 SASRec。

---

## 10. TBD

- dataset-specific negative sampling
- candidate-generation source
- whether multimodal cheap features enter the initial ranker
- whether user memory is fused into SASRec in later experiments
