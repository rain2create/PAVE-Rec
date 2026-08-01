# Module 00B — Shared Component Interfaces
# 共享组件接口与 Ownership

## 1. Purpose

本文档记录 P1-03 已确认的跨组件调用契约，以及 P1-08 补充确认的
`AgentRunRequest`。它只定义组件能看到什么、接收什么、返回什么，以及正常失败
和异常怎样表达；不定义 User Memory、Ranking、Information Need、Segment Value、
Perception 或 Score Update 的真实算法。

公共数据对象以
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md) 为准。

---

## 2. Complexity Boundary

Phase 1 使用以下最小工程约束：

- 接口使用 synchronous `typing.Protocol`。
- 组件不需要继承共同的业务父类。
- 简单操作直接使用显式参数；复杂操作使用 strict/frozen Request/Result。
- 不引入 async controller、dependency-injection framework、plugin registry、
  generic repository、event bus 或通用 `Result[T, E]`。
- Batch 只用在天然需要批量处理的 ranker、stores 和 Segment Value Model。
- Perceiver 一次只观察一个已选 segment。

Phase 4 如果需要 async/concurrent MLLM，通过 adapter 或新的 runtime 讨论引入，
不在 Phase 1 提前增加复杂度。

---

## 3. Shared Interface Types

下方是字段级 contract。它们与公共 Domain Schema 一样使用 strict/frozen
Pydantic v2 models，但不要求单独持久化或携带 `schema_version`。

### AgentRunRequest

```python
class AgentRunRequest:
    run_id: str
    user_id: str
    user_history: tuple[str, ...]
    candidate_ids: tuple[str, ...]
```

P1-08 已确认 Controller 的全部 run input 通过这个 Request 传入。Budget、stop
thresholds、seed、data version 和 components 在构造 Controller 时注入，不在
Request 中重复。`run_id`、`user_id` 和 candidate IDs 必须是非空字符串；
candidate input 非空且不能重复。Request 的 `run_id` 必须与 resolved config、
State、Trace 和 Result 一致。

### ComponentDescriptor

```python
class ComponentDescriptor:
    role: str
    implementation: str
    version: str
```

每个 component Protocol 暴露只读 `descriptor`。P1-08 已确认 Bootstrap 收集全部
descriptor 并在构造 Controller 时注入；P1-07 已确认 descriptors 只在
`AgentRunResult` 保存一次。

`components.<role>` 中的短字符串是 config selector ID，例如 `mock` 或
`in_memory`；`ComponentDescriptor.implementation` 是被 selector 实际构造的
稳定 runtime implementation ID，例如 `MockUserMemory`。后者使用显式常量，不能
通过 reflection 动态生成 import path 或 `__qualname__`。Bootstrap 必须验证
descriptor 的 `role` 与正在组装的 config role 一致，并按 P1-08 typed config 的
固定 role 顺序收集 descriptors。Phase 1 的精确 selector/descriptor/version 表见
[`00_deterministic_mock_scenario.md`](00_deterministic_mock_scenario.md)。

### CandidateScore

```python
class CandidateScore:
    item_id: str
    score: float
```

`CandidateScore` 是接口内的 current-score entry。显式 rank 由
`RecommendationStateBuilder` 按 score 和稳定 tie-break 规则构造。

### ItemFeatureRef

```python
class ItemFeatureRef:
    item_id: str
    feature_ref: ResourceRef | None
```

### ItemSegmentCatalog

```python
class ItemSegmentCatalog:
    item_id: str
    segments: tuple[SegmentMeta, ...]
    segment_proxy_refs: tuple[SegmentProxyRef, ...]
```

Store 对每个请求 item 返回一个 catalog entry。空 `segments` 明确表示该 item
已查询但没有 segment，避免把“空结果”和“Store 静默漏掉 item”混为一谈。

### RecommendationStateBuildRequest

```python
class RecommendationStateBuildRequest:
    schema_version: str
    run_id: str
    user_id: str
    user_memory: UserMemoryView
    initial_ranking: InitialRankingOutput
    current_scores: tuple[CandidateScore, ...]
    item_feature_refs: tuple[ItemFeatureRef, ...]
    segment_catalog: tuple[ItemSegmentCatalog, ...]
    evidence_state: EvidenceState
    observation_state: ObservationState
    max_perception_actions: int
    remaining_perception_actions: int
    step: int
    metadata: JsonObject
```

### PerceptionRequest and PerceptionResult

```python
class PerceptionRequest:
    segment: SegmentMeta
    information_need: InformationNeed
    user_memory: UserMemoryView
    current_item_evidence: ItemEvidenceState
    metadata: JsonObject


class PerceptionResult:
    item_id: str
    segment_id: str
    status: ObservationStatus
    evidence: Evidence | None
    failure_code: str | None
    failure_reason: str | None
    metadata: JsonObject
```

`PerceptionResult.status` 只能是 `succeeded` 或 `failed`：

- `succeeded` 必须包含同 item/segment 的有效 Evidence，failure fields 为 `None`。
- `failed` 不包含 Evidence，并提供非空 failure code/reason。
- `unobserved` 不是一次 Perceiver 调用结果。

正常的无有效输出、解析失败、timeout 等通过 failed result 表达，不用空 Evidence
伪装成功。

### ScoreUpdateRequest

```python
class ScoreUpdateRequest:
    user_memory: UserMemoryView
    initial_ranking: InitialRankingOutput
    previous_scores: tuple[CandidateScore, ...]
    item_feature_refs: tuple[ItemFeatureRef, ...]
    evidence_state: EvidenceState
    metadata: JsonObject
```

Score Updater 返回覆盖全部 candidates 的 `tuple[CandidateScore, ...]`。它不能
静默删除未观察 item。`initial_ranking` 保留 conventional recommender prior，
`previous_scores` 表示本步更新前分数；是否使用 residual 或 unified
architecture 仍为 TBD。

---

## 4. Component Visibility

| Component | Allowed input | Explicitly not required |
|---|---|---|
| UserMemory | user ID, user history | candidates, ranking, perception Evidence |
| InitialRanker | user ID, history, candidate IDs | UserMemoryView, MLLM Evidence |
| ItemFeatureStore | item IDs | Recommendation State, policy logic |
| SegmentStore | item IDs | Observation filtering, selection policy |
| RecommendationStateBuilder | `RecommendationStateBuildRequest` | model internals, Tensor |
| InformationNeedEstimator | complete `RecommendationState` | raw media, model internals |
| SegmentValueModel | `SegmentValueInput` | raw media, MLLM output |
| SegmentPerceiver | `PerceptionRequest` | complete candidate ranking by default |
| EvidenceUpdater | EvidenceState, successful Evidence | raw media, score-update logic |
| ObservationUpdater | ObservationState, PerceptionResult, attempt step | ranking/model logic |
| ScoreUpdater | `ScoreUpdateRequest` | raw media, Observation mutation |
| StopPolicy | confirmed state/value context | model internals |
| TraceWriter | confirmed Trace/Result objects | policy decisions |

Full State is only passed where global decision context is part of the component's
responsibility. Implementations cannot reach into Controller internals or obtain extra
inputs through hidden globals.

---

## 5. Protocol Contracts

所有 Protocol 都包含：

```python
@property
def descriptor(self) -> ComponentDescriptor:
    ...
```

为简洁起见，下方省略重复的 descriptor property。

### User Memory

```python
class UserMemory(Protocol):
    def build_or_update(
        self,
        user_id: str,
        history: tuple[str, ...],
    ) -> UserMemoryView:
        ...
```

Phase 1 使用 `MockUserMemory`。真实 Memory update algorithm 留到对应研究阶段。

### Initial Ranker

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

### Static Stores

```python
class ItemFeatureStore(Protocol):
    def load_refs(
        self,
        item_ids: tuple[str, ...],
    ) -> tuple[ItemFeatureRef, ...]:
        ...


class SegmentStore(Protocol):
    def load_catalog(
        self,
        item_ids: tuple[str, ...],
    ) -> tuple[ItemSegmentCatalog, ...]:
        ...
```

Store 只提供静态 metadata/references，不根据 Observation State 执行策略过滤。
未观察 segment 由已经构造的 Recommendation State 做确定性投影，避免 Store
变成 Agent policy 的一部分。

### Recommendation State Builder

```python
class RecommendationStateBuilder(Protocol):
    def build(
        self,
        request: RecommendationStateBuildRequest,
    ) -> RecommendationState:
        ...
```

### Information Need

```python
class InformationNeedEstimator(Protocol):
    def estimate(
        self,
        state: RecommendationState,
    ) -> InformationNeed:
        ...
```

### Segment Value

```python
class SegmentValueModel(Protocol):
    def predict(
        self,
        request: SegmentValueInput,
    ) -> tuple[SegmentValue, ...]:
        ...
```

Result 必须与 input candidate segments 一一对应，不允许 duplicate、missing 或
extra `(item_id, segment_id)`。Model 返回 tuple 的原始顺序不承载业务语义；
Controller 按 identity 验证 coverage，并在 selection/trace 前归一化到
`request.candidate_segments` 的顺序。空 candidate-segment input 返回空 tuple。

### Perception

```python
class SegmentPerceiver(Protocol):
    def observe(
        self,
        request: PerceptionRequest,
    ) -> PerceptionResult:
        ...
```

### Evidence and Observation Update

```python
class EvidenceUpdater(Protocol):
    def update(
        self,
        state: EvidenceState,
        evidence: Evidence,
    ) -> EvidenceState:
        ...


class ObservationUpdater(Protocol):
    def update(
        self,
        state: ObservationState,
        result: PerceptionResult,
        attempt_step: int,
    ) -> ObservationState:
        ...
```

两者都是纯状态转换：不原地修改输入，不调用 Perceiver，不更新 scores。
P1-05 已确认 `attempt_step = current RecommendationState.step + 1`，并与本次
attempt 完成后重建 State 的 `step` 相同。

### Score Update

```python
class ScoreUpdater(Protocol):
    def update(
        self,
        request: ScoreUpdateRequest,
    ) -> tuple[CandidateScore, ...]:
        ...
```

### Stop Policy and Trace Writer

P1-06 已确认 Stop Policy 的最小 synchronous interface：

```python
class StopPolicy(Protocol):
    def decide_pre_value(
        self,
        state: RecommendationState,
    ) -> StopDecision:
        ...

    def decide_post_value(
        self,
        state: RecommendationState,
        best_segment_value: SegmentValue,
    ) -> StopDecision:
        ...
```

pre-value 只读取 State；post-value 读取 State 和 Controller 已按确定性规则选出的
最佳 `SegmentValue`。Policy 不接收完整 Value batch、Information Need、模型内部
状态或 Controller globals。

P1-07 已确认 Trace Writer 的同步接口：

```python
class TraceWriter(Protocol):
    def write_step(
        self,
        record: AgentStepTrace,
    ) -> None:
        ...

    def write_result(
        self,
        result: AgentRunResult,
    ) -> None:
        ...
```

Writer 每条 JSONL record 写入后 flush。任何 write failure 都抛
`ComponentExecutionError` 并终止 run，不能在 trace 不完整时继续执行 action。
完整 artifact layout 和 replay contract 见
[`00_trace_replay.md`](00_trace_replay.md)。

---

## 6. Error Contract

异常只表达无法作为正常业务结果继续处理的情况：

```text
PaveRecError
├── ContractError
├── ResourceResolutionError
└── ComponentExecutionError
```

- `ContractError`：Schema/invariant/coverage 违规，例如重复 candidate、Value
  output 缺项或 item/segment identity 不一致。
- `ResourceResolutionError`：必需 reference 无法解析、checksum/version 不匹配。
- `ComponentExecutionError`：组件发生未被正常 result contract 表达的执行错误。
- 可预期 Perception failure 返回 `PerceptionResult(status=failed)`，不是异常。

异常不能被静默吞掉，也不能自动转换为空 Evidence、空 scores 或伪成功。
P1-05 已确认 declared exception 终止当前 run；正常
`PerceptionResult(status=failed)` 在提交 failed observation 和 action counters
后可以继续。StopReason 已由 P1-06 确认，terminal trace/result 字段由 P1-07
确认。

业务/运行时 declared exception 在 TraceWriter 健康时写 terminal trace/result。
TraceWriter 自身的 `ComponentExecutionError` 是 P1-09 确认的 artifact-sink 特殊
边界：立即停止、传播异常、不要求损坏的 Writer 再写自己的失败，也不返回
`AgentRunResult`。

P1-06 已确认 action budget 以 `SegmentPerceiver.observe()` 的调用为消费边界：
正常 succeeded/failed result 和 Perceiver declared exception 都消耗一次 action；
Perceiver 调用前的 stop/exception 不消耗，后续 updater exception 不重复消耗。
P1-07 已确认异常路径通过 `AgentStepTrace.action_consumed` 和
`AgentRunResult.attempted_perception_actions` 表达已消费 action。

---

## 7. Empty and Missing Data

- Agent run 的 candidate IDs 为空属于 invalid input。
- Item feature 可以通过 `ItemFeatureRef(feature_ref=None)` 显式表示不可用；
  一旦提供 ResourceRef，解析失败必须抛出 `ResourceResolutionError`。
- Segment Value 的 candidate segments 为空是合法的接口级输入并返回空 tuple；
  Controller runtime 在 pre-value stop 后不会对空 input 调用 Model。
- Stores 对请求中的未知 item 不得静默遗漏；返回值必须覆盖请求，或抛出明确错误。
- Ranker 和 ScoreUpdater 输出必须覆盖全部 candidate IDs，不能静默增删。
- Segment Value 并列时由 Controller 按 `(item_id, segment_id)` 升序打破并列。

---

## 8. Ownership Summary

```text
Perceiver
    → PerceptionResult

ObservationUpdater
    → new ObservationState

EvidenceUpdater (success only)
    → new EvidenceState

ScoreUpdater (success only)
    → new candidate scores

RecommendationStateBuilder
    → new immutable RecommendationState

Controller
    → only orchestrates the confirmed sequence
```

没有任何 component 可以原地修改已经发布的 Domain object。

---

## 9. Code Location

实现阶段使用以下最小布局：

```text
domain/interface_types.py   # Request/Result, CandidateScore, descriptors
errors.py                   # shared exception taxonomy
<capability>/base.py        # capability-specific Protocol
```

例如 `SegmentPerceiver` 放在 `perception/base.py`，`InitialRanker` 放在
`ranking/initial/base.py`。不建立包含所有组件的中央 interface registry。
