# Module 00C — Deterministic Mock Scenario
# Phase 1 确定性 Mock 场景

## 1. Purpose

本文档记录 P1-04 已确认的 canonical Mock fixture、组件查表映射和完整预期运行。
它用于验证 Agent 数据流、状态转换和工程不变量，不是任何真实研究算法的
baseline。

公共对象和组件接口分别以
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md) 和
[`00_component_interfaces.md`](00_component_interfaces.md) 为准。

---

## 2. Boundary

`mock-v1` 遵守以下边界：

- 一个主用户、三个 candidates、每个 candidate 两个 segments。
- 所有 Mock 输出由 versioned fixture 查表得到。
- 主场景不使用 pseudo-random behavior。
- resolved config 和 AgentRunResult 仍记录 seed；canonical fixture 使用
  `seed: 7`，但组件输出不依赖 RNG。
- Mock 映射只为制造可观察、可断言的 Agent 行为，不确定 NTD、Information
  Need、Segment Value、Perception、Evidence aggregation 或 Score Update 的
  真实公式。
- Controller 调用顺序以
  [`08_agent_controller.md`](08_agent_controller.md) 中已确认的 P1-05
  状态机为准；StopReason/threshold semantics 已由 P1-06 确认，Trace JSONL
  schema 已由 P1-07 确认。

Fixture version：

```text
mock-v1
```

---

## 3. Canonical Fixture

### 3.1 Run Input

```text
user_id: user_main
history: (history_01, history_02, history_03)
candidate_ids: (item_a, item_b, item_c)
max_perception_actions: 2
ranking_margin_threshold: 0.10
min_segment_value: 0.15
seed: 7
```

Candidate 和 tuple 顺序固定为 `item_a`、`item_b`、`item_c`。排序仍由 score 和
已确认的 deterministic tie-break 规则决定。

### 3.2 User Memory View

主用户同时表达 stable、emerging 和 fading signals：

| Atom ID | Memory side | Text | State | Strength | Persistence |
|---|---|---|---|---:|---:|
| `pref_plot_twist_long` | long-term | plot twists | stable | 0.90 | 0.95 |
| `pref_slow_drama_long` | long-term | slow drama | fading | 0.55 | 0.80 |
| `pref_plot_twist_short` | short-term | recent suspense | stable | 0.85 | 0.70 |
| `pref_ai_visuals_short` | short-term | AI-generated visuals | emerging | 0.75 | 0.30 |

固定 match signals：

| Long atom | Short atom | Similarity | Classification |
|---|---|---:|---|
| `pref_plot_twist_long` | `pref_plot_twist_short` | 0.93 | stable |
| `None` | `pref_ai_visuals_short` | 0.18 | emerging |
| `pref_slow_drama_long` | `None` | `None` | fading |

Canonical View 的其余字段固定为：

```text
global_drift: 0.20
new_interest_drift: 0.30
drop_interest_drift: 0.25
semantic_profile: "Stable interest in plot twists; emerging interest in AI visuals."
similarity_matrix_ref: None
memory_version: mock-memory-v1
updated_at_ms: None
```

所有 atom 的 `created_at_ms`、`last_seen_at_ms` 和 `embedding_ref` 为 `None`，
metadata 为空 object。这些值只验证 Schema 和消费路径，不表示真实 Memory
update 算法。一次 run 内该 View 保持不变。

### 3.3 Initial Ranking

| Item | Initial score | Initial rank |
|---|---:|---:|
| `item_a` | 0.81 | 1 |
| `item_b` | 0.79 | 2 |
| `item_c` | 0.61 | 3 |

初始 top-1/top-2 margin 为 `0.02`。这个数值只用于制造一次清晰的换位。

### 3.4 Static Stores

每个 item 有两个静态 segment：

| Item | Segment | Start | End |
|---|---|---:|---:|
| `item_a` | `segment_1` | 0 ms | 10000 ms |
| `item_a` | `segment_2` | 10000 ms | 20000 ms |
| `item_b` | `segment_1` | 0 ms | 10000 ms |
| `item_b` | `segment_2` | 10000 ms | 20000 ms |
| `item_c` | `segment_1` | 0 ms | 10000 ms |
| `item_c` | `segment_2` | 10000 ms | 20000 ms |

Item features、segment proxies 和 media 都使用 `ResourceRef`，并固定到
`mock-v1` store/version。In-memory stores 只返回这些静态 entries，不执行
observation filtering 或选择策略。

Reference 采用以下确定性规则，`checksum=None`：

```text
item feature:
  store=mock_item_features, key={item_id}, version=mock-v1

segment proxy:
  store=mock_segment_proxies, key={item_id}/{segment_id}, version=mock-v1

segment media:
  store=mock_media, key={item_id}/{segment_id}, version=mock-v1

user sequence feature:
  store=mock_user_features, key=user_main, version=mock-v1
```

### 3.5 Component Versions

所有 fixture-backed Mock components 和 in-memory stores 都暴露 P1-03 要求的
`ComponentDescriptor`。Config selector、runtime descriptor 和 version 是不同
概念；Bootstrap 使用 selector 选择 constructor，Result 保存实际 descriptor。
Phase 1 按下表固定 descriptor tuple 的顺序和值：

| Order | Role | Config selector | Descriptor implementation | Version |
|---:|---|---|---|---|
| 1 | `user_memory` | `mock` | `MockUserMemory` | `mock-v1` |
| 2 | `initial_ranker` | `mock` | `MockInitialRanker` | `mock-v1` |
| 3 | `item_feature_store` | `in_memory` | `InMemoryItemFeatureStore` | `mock-v1` |
| 4 | `segment_store` | `in_memory` | `InMemorySegmentStore` | `mock-v1` |
| 5 | `state_builder` | `default` | `DefaultRecommendationStateBuilder` | `phase1-v1` |
| 6 | `information_need` | `mock` | `MockInformationNeedEstimator` | `mock-v1` |
| 7 | `segment_value` | `mock` | `MockSegmentValueModel` | `mock-v1` |
| 8 | `perceiver` | `mock` | `MockPerceiver` | `mock-v1` |
| 9 | `evidence_updater` | `mock` | `MockEvidenceUpdater` | `mock-v1` |
| 10 | `observation_updater` | `mock` | `MockObservationUpdater` | `mock-v1` |
| 11 | `score_updater` | `mock` | `MockScoreUpdater` | `mock-v1` |
| 12 | `stop_policy` | `threshold` | `ThresholdStopPolicy` | `phase1-v1` |
| 13 | `trace_writer` | `jsonl` | `JsonlTraceWriter` | `phase1-v1` |

这些 implementation 字符串是稳定显式 ID，并不授权 reflection-based component
loading。Fixture-backed implementations 使用 `mock-v1`；通用 Phase 1 harness
components 使用 `phase1-v1`，不冒用 fixture version。

---

## 4. Deterministic Component Mappings

### 4.1 MockUserMemory

```text
(user_main, canonical history)
    → canonical UserMemoryView
```

未知 fixture key 不返回临时默认值，必须产生明确的 fixture/contract error。

### 4.2 MockInitialRanker

```text
(user_main, canonical history, item_a/item_b/item_c)
    → item_a=0.81, item_b=0.79, item_c=0.61
```

输出覆盖全部且仅覆盖请求 candidates。

### 4.3 In-memory Stores

```text
(item_a, item_b, item_c)
    → one ItemFeatureRef per item
    → one ItemSegmentCatalog with two segments per item
```

返回顺序与请求 item 顺序一致；未知 item 不被静默忽略。

### 4.4 MockInformationNeedEstimator

Estimator 在 `state.user_memory` 中验证 canonical plot-twist atoms 和
`mock-memory-v1`，然后返回固定 need：

```text
need_id: need_plot_twist
concept: narrative surprise
description: Evidence about whether a candidate contains a strong plot twist.
relevant_preference_atom_ids:
  - pref_plot_twist_long
  - pref_plot_twist_short
preference_importance: 0.90
evidence_gap: 0.80
ranking_relevance: 0.95
contrastiveness: 0.70
embedding_ref: None
metadata: {}
```

通过 memory signature 查表只证明组件消费 User Memory；它不是 Information
Need 估计算法。

### 4.5 MockSegmentValueModel

Value Model 对输入中的所有 unobserved `(item, segment)` 一次批量查表：

| Item | Segment | Value |
|---|---|---:|
| `item_a` | `segment_1` | 0.20 |
| `item_a` | `segment_2` | 0.70 |
| `item_b` | `segment_1` | 0.90 |
| `item_b` | `segment_2` | 0.30 |
| `item_c` | `segment_1` | 0.10 |
| `item_c` | `segment_2` | 0.05 |

输出必须与本次 input 一一对应。已经观察的 segment 不会出现在 input，因此也
不会出现在 output；Model 本身不读取或修改 Observation State。

### 4.6 MockPerceiver

Canonical success table 为每个 segment 提供固定 Evidence：

| Selected segment | Evidence ID | Structured attributes |
|---|---|---|
| `item_a.segment_1` | `evidence_a_1` | `{"pacing": "fast"}` |
| `item_a.segment_2` | `evidence_a_2` | `{"plot_twist": "weak"}` |
| `item_b.segment_1` | `evidence_b_1` | `{"plot_twist": "strong"}` |
| `item_b.segment_2` | `evidence_b_2` | `{"ai_visuals": "strong"}` |
| `item_c.segment_1` | `evidence_c_1` | `{"plot_twist": "absent"}` |
| `item_c.segment_2` | `evidence_c_2` | `{"slow_drama": "strong"}` |

每个 Evidence 使用对应 table identity，`confidence=0.90`、`source=mock-v1`，
`text_summary` 是 attribute 的固定人类可读表达，raw/embedding refs 为 `None`，
metadata 为空 object。Failure variant 可以覆盖某个 entry 并返回
`PerceptionResult(status=failed)`；不能返回空 Evidence 伪装成功。

### 4.7 MockEvidenceUpdater

成功时：

```text
append Evidence to the matching ItemEvidenceState
reject duplicate evidence_id
rebuild a new EvidenceState
```

`aggregated_attributes` 只记录确定性的 Mock bookkeeping，例如有序
`mock_evidence_ids`，不实现语义聚合公式。

失败时 Controller 不调用 EvidenceUpdater。

### 4.8 MockObservationUpdater

根据 `PerceptionResult` 把唯一目标 segment 从 `unobserved` 转成
`succeeded` 或 `failed`，增加 attempt count，并返回新的 ObservationState。
`attempt_step = current RecommendationState.step + 1`，第一次 attempt 为 1。

### 4.9 MockScoreUpdater

Updater 从 initial prior 和累计 Evidence IDs 计算固定 fixture delta：

| Evidence ID | A delta | B delta | C delta |
|---|---:|---:|---:|
| `evidence_a_1` | +0.01 | 0.00 | 0.00 |
| `evidence_a_2` | -0.03 | 0.00 | 0.00 |
| `evidence_b_1` | 0.00 | +0.08 | 0.00 |
| `evidence_b_2` | 0.00 | +0.02 | 0.00 |
| `evidence_c_1` | 0.00 | 0.00 | -0.01 |
| `evidence_c_2` | 0.00 | 0.00 | 0.00 |

```text
mock_score(item)
    = initial_fixture_score(item)
    + sum(configured delta for cumulative evidence IDs)
```

这是测试查表，不是对 residual architecture 的研究选择。Updater 每次覆盖所有
candidates；没有 Evidence 的 item 保留 initial prior。

---

## 5. Expected Canonical Run

### Step 0 State

```text
ranking: item_a(0.81) > item_b(0.79) > item_c(0.61)
remaining actions: 2
state step: 0
observed segments: none
information need: need_plot_twist
```

Value Model 收到全部六个 unobserved segments。全局最大值是：

```text
item_b.segment_1 = 0.90
```

因此首先选择当前 rank-2 item 的 segment。Perceiver 返回
`evidence_b_1`，Observation 变为 succeeded，更新后：

```text
scores: item_b=0.87, item_a=0.81, item_c=0.61
ranking: item_b > item_a > item_c
remaining actions: 1
rebuilt state step: 1
```

### Step 1 State

`item_b.segment_1` 已经被观察，不再进入 candidate-segment input。剩余五个
segment 中全局最大值是：

```text
item_a.segment_2 = 0.70
```

Perceiver 返回 `evidence_a_2`，更新后：

```text
scores: item_b=0.87, item_a=0.78, item_c=0.61
ranking: item_b > item_a > item_c
remaining actions: 0
rebuilt final state step: 2
```

主场景中初始 margin 为 0.02、第一次 action 后为 0.06、第二次 action 后为
0.09，均低于 0.10；每轮最大 segment value 分别为 0.90 和 0.70，均不低于
0.15。因此不会被 certainty/low-value 提前终止，并最终以
`budget_exhausted` 结束。

### Proven Behaviors

该两步运行必须证明：

- Information Need 读取 canonical User Memory signature。
- Segment Value 对所有可用 `(item, segment)` 进行一个 batch 的全局比较。
- rank-2 item 可以先于 rank-1 item 被感知。
- 成功 perception 产生结构化 Evidence。
- Evidence 可以改变 scores 并触发 ranking 换位。
- 已观察 segment 不会再次被选择。
- 未观察 item 保留 initial ranking prior。
- 两次 action 后 budget 精确归零。

---

## 6. Test Variants

除 canonical run 外，Phase 1 测试使用共享 fixture 的最小显式 override：

| Variant | Override | Intended behavior |
|---|---|---|
| `zero_budget` | max actions = 0 | 不调用 Perceiver |
| `high_certainty` | margin threshold = 0.01 | certainty stop path |
| `no_segments` | all catalogs contain empty segment tuples | no-unobserved path |
| `low_values` | maximum available value < 0.15 | low-value path |
| `perception_failed` | `item_b.segment_1` returns `mock_timeout` failed result | failed observation, no Evidence |
| `component_exception` | Perceiver raises configured `ComponentExecutionError` | exception stop/error path |

这些 variants 只预留输入和组件结果。P1-05 已确认正常 failed result 提交
failed observation/counters 后可以继续，declared component exception 终止 run。
P1-06 已确认 StopReason 和 reason priority；trace assertions 在 P1-07 确认后
由 P1-09 实现。空 candidate input 属于独立 contract test，不伪装成 canonical
Mock run。

`perception_failed` 的 result 固定为 `evidence=None`、
`failure_code="mock_timeout"` 和明确的 fixture failure reason。
`component_exception` 是专门测试异常控制流的 fault injection；它不把可预期
timeout 从 failed result 改成 exception。两者都发生在 Perceiver 调用边界，
因此各消耗一次 action budget；不新增 cost/telemetry schema。

---

## 7. Versioning and Golden Artifacts

- Fixture specification 和 semantic expected run 纳入 Git，version 为
  `mock-v1`。
- 实现阶段将机器可读 fixture 放在
  `tests/fixtures/mock/v1/scenario.json`，并将 canonical expected artifacts 固定为：

  ```text
  tests/fixtures/mock/v1/expected/resolved_config.json
  tests/fixtures/mock/v1/expected/trace.jsonl
  tests/fixtures/mock/v1/expected/result.json
  ```

- P1-07 已确认 JSONL schema；实现阶段生成三行 canonical golden trace：
  两条 completed action records 和一条 pre-value budget stop record。
- Golden run ID 固定为 `mock-v1-golden`，Git metadata 固定注入 `None`，三个
  expected artifacts 使用 P1-07 canonical UTF-8/LF serializer 做 byte-exact
  comparison，并另外断言完整 JSON round trip。
- Fixture 内容发生有意的行为变化时创建新版本，不静默改写旧 golden contract。
