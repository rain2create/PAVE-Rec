# Module 02 — SASRec Cheap Initial Ranking
# SASRec 低成本初始排序模块

## 1. 模块目标 Purpose

在不进行昂贵视频多模态理解的前提下，先得到一个 initial candidate ranking。

这个模块提供一个 conventional recommender prior，作为后续 Agent 主动感知的起点。

V1 默认：

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

V1 先以标准 sequential recommendation 为主。

---

## 3. 输出 Output

```python
@dataclass
class InitialRankingOutput:
    scores: dict[str, float]
    ranking: list[str]
    user_sequence_embedding: Tensor | None
```

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

V1 保持两者分离。

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

```python
class InitialRanker:
    def score(
        self,
        user_id: str,
        sequence: list[str],
        candidate_ids: list[str],
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
optional hidden state
```

---

## 9. V1 Goal

支持：

```bash
python scripts/train_sasrec.py
python scripts/run_mock_agent.py
```

Mock agent 可以直接消费真实 SASRec score。

---

## 10. TBD

- dataset-specific negative sampling
- candidate-generation source
- whether multimodal cheap features enter the initial ranker
- whether user memory is fused into SASRec in later experiments
