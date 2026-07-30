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

### Stage 4 — Build Oracle/Teacher Perception Data

对 sampled recommendation state 和 segment：

- perceive segment
- obtain evidence
- update ranking
- calculate actual recommendation gain

### Stage 5 — Train Segment Value Model

学习：

```text
state + information need + cheap segment proxy
→ expected recommendation gain
```

### Stage 6 — Train Score Updater / Reranker

具体设计当前：

```text
TBD
```

### Stage 7 — Integrate End-to-End Agent

运行完整 active-perception loop。

### Stage 8 — Optional RL

只有 supervised system 稳定之后再考虑。

---

## 3. Recommendation Metrics

根据 dataset/task 支持：

```text
HR@K
NDCG@K
MRR
Recall@K
```

---

## 4. Perception Efficiency Metrics

重点评估：

```text
ranking quality vs number of perceived segments
ranking quality vs MLLM token cost
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
Proposed Segment Value Model
Oracle segment selection
```

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
w/o Segment Value Model
w/o Active Stop
w/o Evidence Update
fixed-frame perception
full-video perception
```

---

## 7. Memory Evaluation

Potential measures：

```text
next-item recommendation
interest classification agreement
emerging-interest detection
fading-interest detection
profile freshness
```

具体 memory benchmark 当前：

```text
TBD
```

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
config
seed
model versions
checkpoint IDs
dataset split
budget
ranking metrics
perception cost metrics
agent traces
```

---

## 11. TBD

- exact target dataset
- exact ground-truth definition
- exact value-model label
- exact oracle construction
- final baselines
- whether to include RL
