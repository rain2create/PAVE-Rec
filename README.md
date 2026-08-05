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
│   ├── 00_shared_domain_schemas.md
│   ├── 00_component_interfaces.md
│   ├── 00_deterministic_mock_scenario.md
│   ├── 00_trace_replay.md
│   ├── 01_dynamic_hybrid_user_memory.md
│   ├── ...
│   └── 10_evaluation_and_training_plan.md
│
├── todo/
│   ├── README.md
│   ├── implementation_roadmap.md
│   ├── phase_1_discussion.md
│   └── phase_2_discussion.md
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
验收标准见 `todo/implementation_roadmap.md`；已确认的 Phase 1/2 Decision Records
分别见 `todo/phase_1_discussion.md` 和 `todo/phase_2_discussion.md`。

Phase 1 的公共 Schema、组件接口和确定性测试剧本分别以
`docs/00_shared_domain_schemas.md`、`docs/00_component_interfaces.md` 和
`docs/00_deterministic_mock_scenario.md` 为准；Trace/Replay contract 以
`docs/00_trace_replay.md` 为准。配置继承、Bootstrap、`AgentRunRequest`、共享
runner 和 CLI contract 已由 `todo/phase_1_discussion.md` 的 P1-08 Decision
Record 确认；测试矩阵、quality gates、CI 和 Phase 1 Definition of Done 已由
P1-09 Decision Record 确认。Phase 1 已完成实现和验收；P1-XG-01 已统一 segment
identity、descriptor、canonical serialization、failure lifecycle 和 temporary-project
testing 语义。Phase 2 的 P2-00—P2-08 与 P2-XG-01 也已全部确认，并据此实现
offline data and persistent Store。Phase 2 baseline、portable golden、
persistent Store Agent smoke、本地 quality gates 和远端 Ubuntu/Windows CI matrix
已全部通过；Phase 2 Definition of Done 已满足，状态正式记为 `Completed`。

Phase 3 的 P3-00—P3-08 与 P3-XG-01 也已全部确认：第一条真实主线使用 pinned Tsinghua
ShortVideo sampled release，构建 versioned derived sequence、dataset-specific SASRec、Dynamic
Hybrid Memory、full-catalog evaluation 和 unchanged Controller zero-budget Cheap Path。跨 Gate
审计已确认不修改 P1 public interfaces/Controller 或 P2 exact-release data plane；Phase 3 当前为
`Local Implementation Complete / Remote CI Pending`：P3-01—P3-08 的真实单 seed lifecycle、MostPop/SASRec
full-catalog evaluation、Memory aggregate audit、zero-budget Agent run/replay 和 Windows long-path 回归均已
跑通。本地验收为 `275 passed, 2 skipped`、branch coverage `90.03%`、Ruff clean；由于 P3-08 还要求同一
candidate commit 的远端 required CI，因此现在仍不标记为 `Completed`。完整约定与精确产物引用见
`todo/phase_3_discussion.md`。

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
# validate input, then initialize cheap/static inputs once
user_memory_view = user_memory.build_or_update(user_id, tuple(user_history))
item_feature_refs = item_store.load_refs(tuple(candidate_ids))
segment_catalog = segment_store.load_catalog(tuple(candidate_ids))
initial_ranking = sasrec_ranker.score(
    user_id=user_id,
    sequence=tuple(user_history),
    candidate_ids=tuple(candidate_ids),
)
scores = scores_from(initial_ranking)
evidence_state = EvidenceState.empty(candidate_ids)
observation_state = ObservationState.empty(candidate_ids)
max_perception_actions = config.agent.max_perception_actions
step = 0
state = recommendation_state_builder.build(...)

while True:
    enforce_budget_derived_safety_guard()

    pre_decision = stop_policy.decide_pre_value(state)
    if pre_decision.stop:
        return terminal_result(state, pre_decision)

    information_need = information_need_estimator.estimate(state)
    candidate_segments = candidate_segments_from(state)
    values = segment_value_model.predict(
        SegmentValueInput(
            state=state,
            information_need=information_need,
            candidate_segments=candidate_segments,
        )
    )
    validate_value_coverage(candidate_segments, values)
    best = deterministic_argmax(values)

    post_decision = stop_policy.decide_post_value(state, best)
    if post_decision.stop:
        return terminal_result(state, post_decision)

    result = perceiver.observe(
        PerceptionRequest(
            segment=find_segment_meta(segment_catalog, best),
            information_need=information_need,
            user_memory=user_memory_view,
            current_item_evidence=state_candidate(state, best).evidence,
            metadata={},
        )
    )

    attempt_step = state.step + 1
    next_observation_state = observation_updater.update(
        state=observation_state,
        result=result,
        attempt_step=attempt_step,
    )

    if result.status == ObservationStatus.SUCCEEDED:
        next_evidence_state = evidence_updater.update(
            evidence_state,
            result.evidence,
        )
        next_scores = score_updater.update(
            ScoreUpdateRequest(
                user_memory=user_memory_view,
                initial_ranking=initial_ranking,
                previous_scores=scores,
                item_feature_refs=item_feature_refs,
                evidence_state=next_evidence_state,
                metadata={},
            )
        )
    else:
        next_evidence_state = evidence_state
        next_scores = scores

    observation_state = next_observation_state
    evidence_state = next_evidence_state
    scores = next_scores
    step = attempt_step
    state = recommendation_state_builder.build(...)
    emit_completed_transition(...)
```

以上只展示主控制流。正常 failed result 消耗 action、记录 failed observation
后可以继续；declared component exception 终止 run。完整状态机以
`docs/08_agent_controller.md` 为准，公共对象和组件契约分别以
`docs/00_shared_domain_schemas.md`、`docs/00_component_interfaces.md` 为准。

---

## 6. 模块说明文档 Module Documents

- `docs/Intro.md`
- `docs/00_shared_domain_schemas.md`
- `docs/00_component_interfaces.md`
- `docs/00_deterministic_mock_scenario.md`
- `docs/00_trace_replay.md`
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

---

## 7. 活跃规划 Active Planning

- `todo/implementation_roadmap.md`
- `todo/phase_1_discussion.md`
- `todo/phase_2_discussion.md`
- `todo/phase_3_discussion.md`

`todo/` 中的内容用于逐项讨论，并不自动代表已经确认的研究或实现决策。

---

## 8. Phase 1 Deterministic Mock Runtime

Phase 1 提供离线、CPU-only 的完整确定性 Agent 闭环。当前实现只使用 versioned
`mock-v1` fixture，不包含真实 SASRec、MLLM 或最终研究算法。

安装开发依赖并运行 canonical scenario：

```bash
python -m pip install -e ".[dev]"
python -m pave_rec.cli.run_mock --config configs/mock.yaml
```

也可以直接调用共享 Python API：

```python
from pave_rec.runner import run_from_config

result = run_from_config("configs/mock.yaml")
```

每次完整运行写入：

```text
runs/<run_id>/resolved_config.json
runs/<run_id>/trace.jsonl
runs/<run_id>/result.json
```

Saved-output replay 不会重新调用任何 Agent component：

```python
from pave_rec.agent.replay import replay_run

result = replay_run("runs/<run_id>")
```

本地质量门：

```bash
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q --cov=pave_rec --cov-branch --cov-report=term-missing
```

---

## 9. Phase 2 Offline Data Plane

Phase 2 提供 offline、CPU-only、无媒体解码的结构化 preprocessing baseline：

```bash
python -m pave_rec.cli.preprocess --config configs/preprocessing/fixture.yaml
```

共享 Python API 返回 exact release handoff：

```python
from pave_rec.preprocessing import preprocess_from_config

result = preprocess_from_config("configs/preprocessing/fixture.yaml")
```

`result.release_ref` 与同一 validated root registry 交给 `ReleaseLoader`，构造一个由
filesystem resolver、Item Feature Store 和 Segment Store 共享的 immutable
`LoadedRelease`。Runtime 不扫描 `latest`、不按 mtime 选择版本，也不在 online Agent
loop 内执行切分或批量特征提取。Fixture invocation 只用于复现 Phase 2 contract；它不
代表最终数据集、segmentation、proxy feature 或 embedding 研究方案。

---

## 10. 当前明确保留为 TBD 的研究问题

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
各项 TBD 的第一条 baseline 和后续研究阶段归属见
`todo/implementation_roadmap.md` 的 `Deferred Research Ownership`，阶段归属不代表具体
公式、模型或阈值已经确认。
