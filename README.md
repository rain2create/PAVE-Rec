# Personalized Active Video Perception for Agentic Recommendation
# 面向推荐决策的个性化主动视频感知 Agent

## 1. 项目目标 Project Goal

构建一个在 **MLLM 感知预算有限** 的条件下进行主动多模态感知的 Agentic Recommender。

系统不应该在推荐开始前就完整理解所有候选视频，而应该：

1. 构建动态的用户偏好状态 `Dynamic User Preference State`。
2. 使用传统序列推荐模型，以较低成本得到初始排序 `Cheap Initial Ranking`。
3. 检查当前推荐状态 `Recommendation State`，判断当前排序还缺什么信息。
4. 预测哪个未观察视频片段 `segment` 最有可能改善当前推荐决策。
5. 只把昂贵的 MLLM 感知预算花在这个片段上。
6. 将新的多模态理解结果转化为结构化推荐证据 `Recommendation Evidence`。
7. 更新 item score 并重新排序。
8. 重复上述过程，直到排序已经足够确定，或者感知预算耗尽。

整体核心 loop：

```text
Dynamic Hybrid User Memory
        +
SASRec Initial Ranking
        ↓
Recommendation State
        ↓
Information Need
        ↓
Should Stop?
   /          \
 Yes           No
  |             ↓
Final      Segment Value Model
Ranking          ↓
          select (item, segment)
                 ↓
          MLLM Perception
                 ↓
          Evidence Update
                 ↓
          Score Update
                 ↓
              Re-rank
                 ↓
       back to Recommendation State
```

---

## 2. 工程设计原则 Engineering Principles

### 2.1 研究决策与工程骨架分离

如果某个方法目前还没有最终确定，则代码层面应该：

- 先定义清晰 interface
- 提供简单 baseline implementation
- 不要因为 Codex 方便实现，就默认把某个尚未讨论清楚的方法变成最终研究方案

所有尚未确定的研究选择统一标记为：

```text
TBD
```

### 2.2 Cheap path 与 Expensive path 分离

Cheap path 包括：

- 用户行为序列模型
- embedding
- lightweight item features
- lightweight segment proxy features
- 小型 ranking/value models

Expensive path 包括：

- 只对被选中的 segment 运行 MLLM perception

### 2.3 Perception 与 Ranking 分离

MLLM 的主要职责应该是输出：

```text
Structured Recommendation Evidence
```

而不是直接输出最终 recommendation score。

除非后续专门做 ablation，否则 V1 不应该让 MLLM 直接完成最终排序。

### 2.4 V1 先把整个 loop 跑通

在真实模型全部接入之前，代码库必须支持：

```text
mock user state
mock candidate set
mock SASRec scores
mock segment proxies
mock value scores
mock MLLM evidence
mock score update
```

V1 的主要目标不是追求效果，而是验证：

- interfaces
- state transitions
- logging
- reproducibility
- agent loop correctness

---

## 3. 工程目录 Repository Structure

目标结构如下。具体实现文件在对应阶段创建，不提前放置无行为的代码空壳。

```text
PAVE-Rec/
├── README.md
├── pyproject.toml
│
├── docs/
│   ├── Intro.md
│   ├── 01_dynamic_hybrid_user_memory.md
│   ├── ...
│   ├── 10_evaluation_and_training_plan.md
│   └── implementation_roadmap.md
│
├── configs/
│   ├── base.yaml
│   ├── mock.yaml
│   └── experiments/
│
├── src/
│   └── pave_rec/
│       ├── domain/                  # shared schemas
│       ├── user_memory/
│       │   └── hybrid/
│       ├── ranking/
│       │   ├── initial/
│       │   │   └── sasrec/
│       │   └── update/
│       ├── recommendation_state/
│       ├── information_need/
│       ├── segment_value/
│       ├── perception/
│       ├── stores/
│       ├── agent/
│       ├── preprocessing/
│       ├── training/
│       ├── evaluation/
│       └── cli/                     # thin reproducible entry points
│
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
│
├── data/
│   ├── raw/
│   ├── interim/
│   └── processed/
│
├── artifacts/
│   ├── features/
│   ├── checkpoints/
│   └── oracle/
│
└── runs/
```

所有可复用 Python 逻辑都放在 `src/pave_rec/`。`domain/` 只定义公共领域
对象；各功能模块通过 interface 隔离 Mock、Baseline 和 Learned
implementations；`agent/` 负责编排；`cli/` 只提供可复现实验入口。

`data/`、`artifacts/` 和 `runs/` 中的本地内容默认不进入 Git。具体阶段和
验收标准见 `docs/implementation_roadmap.md`。

---

## 4. 核心数据流 Core Data Flow

```text
User Historical Interactions
        │
        ├───────────────→ SASRec
        │                    ↓
        │             Initial Candidate Scores
        │
        └───────────────→ Dynamic Hybrid Memory
                             ↓
                      User Preference State

Candidate Videos
        ↓
Cheap Item Features
        ↓
Initial Ranking

Candidate Videos
        ↓
Segmentation
        ↓
Cheap Segment Proxy Features

User Preference State
+ Current Scores
+ Evidence State
+ Budget
        ↓
Recommendation State
        ↓
Information Need
        ↓
Segment Value Model
        ↓
Best (item, segment)
        ↓
MLLM Perception
        ↓
Structured Evidence
        ↓
Score Update
        ↓
Rerank
```

---

## 5. 主运行逻辑 Main Runtime Pseudocode

```python
user_state = user_memory.build_or_update(user_history)

candidate_features = item_store.load(candidate_ids)
segment_proxies = segment_store.load(candidate_ids)

scores = sasrec_ranker.score(
    user_id=user_id,
    sequence=user_history,
    candidate_ids=candidate_ids,
)

evidence_state = EvidenceState.empty(candidate_ids)
budget = config.agent.max_perception_steps

while True:
    state = recommendation_state_builder.build(
        user_state=user_state,
        candidate_ids=candidate_ids,
        current_scores=scores,
        evidence_state=evidence_state,
        remaining_budget=budget,
    )

    if stop_policy.should_stop(state):
        break

    information_need = information_need_estimator.estimate(state)

    candidate_segments = segment_store.get_unobserved_segments(
        candidate_ids=candidate_ids,
        evidence_state=evidence_state,
    )

    values = segment_value_model.predict(
        state=state,
        information_need=information_need,
        candidate_segments=candidate_segments,
    )

    selected = values.argmax()

    evidence = perceiver.observe(
        item_id=selected.item_id,
        segment_id=selected.segment_id,
        information_need=information_need,
        user_state=user_state,
        current_evidence=evidence_state,
    )

    evidence_state.update(evidence)

    scores = score_updater.update(
        user_state=user_state,
        candidate_features=candidate_features,
        previous_scores=scores,
        evidence_state=evidence_state,
    )

    budget -= 1

final_ranking = reranker.rank(scores)
```

---

## 6. 模块说明文档 Module Documents

- `docs/Intro.md`
- `docs/01_dynamic_hybrid_user_memory.md`
- `docs/02_sasrec_initial_ranking.md`
- `docs/03_recommendation_state.md`
- `docs/04_information_need.md`
- `docs/05_segment_value_model.md`
- `docs/06_mllm_perception.md`
- `docs/07_evidence_score_update.md`
- `docs/08_agent_controller.md`
- `docs/09_offline_preprocessing.md`
- `docs/10_evaluation_and_training_plan.md`
- `docs/implementation_roadmap.md`

---

## 7. 当前明确保留为 TBD 的研究问题

下面这些内容暂时不应该被 Codex 写死：

- exact video segmentation strategy
- exact preference atom extraction algorithm
- exact long/short matching threshold
- memory decay / promote thresholds
- exact information-need scoring formula
- value-model neural architecture
- expected recommendation gain label
- score-update architecture
- whether uncertainty uses margin only or richer uncertainty
- whether RL is needed after supervised value learning

这些只能作为 configurable research choices，而不能因为 V1 实现方便就默认成为最终方案。
