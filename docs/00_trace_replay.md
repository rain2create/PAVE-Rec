# Module 00D — Trace, Replay, and Reproducibility
# Phase 1 Trace、回放与可复现性

## 1. Purpose

本文档记录 P1-07 已确认的 Agent trace、final result、run artifacts 和 deterministic
replay contract。

公共 State/Decision schema、组件接口和 Controller 状态机分别以
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md)、
[`00_component_interfaces.md`](00_component_interfaces.md) 和
[`08_agent_controller.md`](08_agent_controller.md) 为准。

P1-07 不增加 manifest、event bus、timing/cost telemetry、raw model payload 或
新的日志框架。

---

## 2. Run Directory

每次完整运行使用：

```text
runs/<run_id>/
├── resolved_config.json
├── trace.jsonl
└── result.json
```

普通 run ID 使用：

```text
YYYYMMDDTHHMMSSZ-<8 lowercase hexadecimal characters>
```

- 时间部分使用 UTC。
- run ID 不包含 user ID、dataset 名或其他业务数据。
- canonical golden run 固定使用 `mock-v1-golden`。
- 已存在的 run directory 不能被静默覆盖。
- P1-08 已确认 runner 使用独占目录创建：显式 ID 冲突时报错，自动 ID 碰撞时
  重新生成，任何路径都不覆盖已有目录。

---

## 3. Resolved Configuration

`resolved_config.json` 是完成单父继承合并和 validation 后的完整 typed config
snapshot，不是原始 YAML 的拷贝。

要求：

- 使用下方唯一的 canonical JSON serialization。
- 明确保留 `null`，不依赖隐式默认值重建配置。
- 保存最终实际 run ID 和规范化项目相对路径，不保存本机绝对路径。
- 不保存 API key、token 或其他 secret。
- replay 读取 resolved config，不解析原始配置文件。
- 由 P1-08 runner 在 Controller 启动前写入；Controller 和 TraceWriter 都不修改。

### 3.1 Canonical JSON Serialization

Phase 1 的 byte-exact golden 和跨平台 replay 统一使用以下字节 contract：

1. Pydantic objects 先执行
   `model_dump(mode="json", exclude_none=False)`；resolved config 使用等价的
   validated JSON-mode payload。
2. 所有 JSON 使用 UTF-8、无 BOM、`ensure_ascii=False`、`allow_nan=False` 和
   `sort_keys=True`。
3. `resolved_config.json` 和 `result.json` 使用 `indent=2`，文件末尾恰好一个
   `\n`。两者在同一 run directory 内先写临时文件，再原子提交目标文件；不得让
   半截 JSON 占用正式目标名。
4. `trace.jsonl` 每条记录使用 compact separators `(",", ":")`，每个 object
   恰好占一行并以一个 `\n` 结束。实现必须显式写 LF，不能依赖 Windows text-mode
   newline conversion。
5. Repository `.gitattributes` 固定 JSON/JSONL/YAML 为 LF，避免 checkout 改写
   golden bytes。
6. JSON object keys 由 serializer 排序；tuple/list 的业务顺序由公共 Schema 的
   canonical ordering、Controller projection 和固定 descriptor role order决定，
   不能通过 `sort_keys` 替代 collection ordering。

普通运行和 golden test 使用同一个 serializer；测试不能维护第二套“只为通过
golden”的编码逻辑。

---

## 4. Trace Granularity

`trace.jsonl` 每次 decision-loop 进入写一条 `AgentStepTrace`，不是细粒度
event stream。Controller one-time initialization 内的 declared component failure
是唯一允许在 decision-loop 之前写入的 terminal step record。

一次 record 可以表达：

- completed perception transition
- normal failed-perception transition
- pre-value stop
- post-value stop
- declared component failure
- safety-limit termination

Canonical `mock-v1` 固定三行：

```text
decision 0: first completed action
decision 1: second completed action
decision 2: pre-value budget_exhausted
```

Zero-budget run 只有一条 pre-value terminal record。

---

## 5. AgentStepTrace

```python
class AgentStepTrace:
    schema_version: str
    run_id: str
    decision_index: int

    state_before: RecommendationState | None
    information_need: InformationNeed | None
    segment_values: tuple[SegmentValue, ...] | None

    selected_segment: SegmentMeta | None
    selected_segment_value: SegmentValue | None

    perception_result: PerceptionResult | None
    state_after: RecommendationState | None

    action_consumed: bool
    stop_decision: StopDecision | None
    metadata: JsonObject
```

不增加 `TraceOutcome`、`StopStage` 或独立 `AgentError`。执行到哪个阶段由字段
presence、`action_consumed` 和已确认的 `StopReason` 唯一确定。

Declared error 的结构化信息保存在
`StopDecision(reason=component_failure).details`，不能藏在 metadata 或只写自由
文本日志。

---

## 6. Chained State Storage

Trace 使用链式 State，避免相邻 JSONL lines 重复保存同一个完整 State：

```text
first record with a valid State:
    state_before = step-0/current State

completed transition:
    state_after = newly rebuilt State

later record:
    state_before = None
    current State = previous record.state_after

terminal record:
    state_after = None unless the terminal path produced a new valid State
```

具体规则：

- 第一条拥有合法 current State 的 record 必须保存 `state_before`。
- 后续 record 的 current State 从上一条非空 `state_after` 得到，
  `state_before` 必须为 `None`。
- Zero-budget、first-iteration certainty/no-segments/low-value stop 必须保存
  step-0 `state_before`，因为之前没有 State record。
- initialization component failure 可以同时没有 before/after State。
- ScoreUpdater failure 已确认可以保存包含新 Evidence/Observation、旧 scores 和
  已扣 action 的合法 terminal `state_after`。
- Result 为了可以独立查看，会再保存一份 final State；不会为每个中间 State
  产生第二份副本。

每个保存的 State 都是完整 `RecommendationState`，不另建 summary/delta schema。

---

## 7. Decision Payload Rules

### Completed successful action

```text
information_need: present
segment_values: present and non-empty
selected_segment/value: present
perception_result: succeeded
state_after: present
action_consumed: true
stop_decision: None
```

### Completed normal failed action

```text
information_need: present
segment_values: present and non-empty
selected_segment/value: present
perception_result: failed
state_after: present
action_consumed: true
stop_decision: None
```

### Pre-value stop

```text
information_need/segment_values/selection/perception_result: None
state_after: None
action_consumed: false
stop_decision: terminal pre-value reason
```

### Post-value stop

```text
information_need: present
segment_values: present and non-empty
selected_segment/value: present
perception_result/state_after: None
action_consumed: false
stop_decision: max_segment_value_too_low
```

### Declared component failure

- `stop_decision.reason=component_failure`。
- Perceiver 调用前失败时 `action_consumed=false`。
- Perceiver 调用或后续 updater 阶段失败时 `action_consumed=true`。
- `perception_result` 只在 Perceiver 已正常返回时存在。
- `state_after` 只在 Controller 能构造满足全部 invariants 的 terminal State 时
  存在。

### Controller initialization component failure

UserMemory、Item/Segment Store、InitialRanker 或初始 StateBuilder 在
`Controller.run()` 的 one-time initialization 中抛出 declared exception 时，
如果 TraceWriter 正常，固定写一条 terminal record：

```text
decision_index: 0
state_before/state_after: None
information_need/segment_values/selection/perception_result: None
action_consumed: false
stop_decision.reason: component_failure
```

对应 `AgentRunResult` 使用 `succeeded=false`、`final_state=None`、
`attempted_perception_actions=0` 和 `trace_record_count=1`。这与 Bootstrap
constructor failure 不同：后者发生在 Controller 前，只留下
`resolved_config.json`，不伪造 trace/result。TraceWriter 自身失败则遵守 P1-09
特殊边界，不要求再写本记录或 Result。

### Safety termination

```text
action_consumed: false
stop_decision.reason: safety_limit_reached
```

---

## 8. Segment Values and Large Resources

Value Model 被调用后，trace 保存本轮全部 `SegmentValue`，不能只保存最大值。
Replay 用它验证 coverage、argmax、tie-break 和 low-value stop。

Controller 先按复合 identity 验证 Value coverage，再把 values 归一化到按
`(item_id, segment_id)` 排列的 `CandidateSegmentRef` input 顺序。Model 返回的
原始 tuple 顺序不进入 trace，也不影响 golden bytes。

`SegmentValue` 是轻量 JSON object。Trace 不保存：

```text
feature Tensor
embedding array
raw media
raw MLLM response
frame/token/latency/cost placeholder
```

Features、embeddings、media 和 raw output 只通过已有 `ResourceRef` 关联。

Phase 1 使用 inline SegmentValue。未来只有在真实 per-run candidate-segment
规模经 profiling 证明存在 I/O 问题后，才讨论独立 artifact/reference；P1-07
不提前增加该结构。

---

## 9. AgentRunResult

```python
class AgentRunResult:
    schema_version: str
    run_id: str
    succeeded: bool

    final_state: RecommendationState | None
    stop_decision: StopDecision
    attempted_perception_actions: int
    trace_record_count: int

    seed: int
    data_version: str
    component_descriptors: tuple[ComponentDescriptor, ...]

    git_commit: str | None
    git_dirty: bool | None
    metadata: JsonObject
```

Result 不重复保存 final ranking；它由 `final_state.candidates` 的 current ranks
得到。

规则：

- 正常 policy stop 的 `succeeded=True`。
- `component_failure` 和 `safety_limit_reached` 的 `succeeded=False`。
- 正常完成的 run 必须包含 `final_state`。
- initialization component failure 可以没有 `final_state`。
- `attempted_perception_actions` 是 run 实际消耗的 action 数；exceptional
  terminal path 中它可以比 `final_state.step` 大 1。
- `trace_record_count` 必须等于成功写入并属于该 run 的 JSONL record 数量。
- Result 的 stop decision 必须等于最后一次 terminal trace decision。

---

## 10. Reproducibility Fields

每个 `result.json` 必须保存：

- seed
- data/fixture version
- 全部 runtime component descriptors
- Git commit field
- worktree dirty field

`git_commit` 字段必须存在；无法获得 Git metadata 时允许为 `None`。
`git_dirty=True` 不阻止 run，但表示仅凭 commit 不能完全重建当前 source state。

Component descriptors 只在 Result 保存一次，不在每条 trace line 重复。
Resolved config 保存所有控制参数和 implementation selections。

Descriptor tuple 使用
[`00_deterministic_mock_scenario.md`](00_deterministic_mock_scenario.md) 3.5 节的
固定 role 顺序；config selector ID 与 runtime descriptor implementation ID 不得
混用。

Canonical golden test 不读取当前 worktree 的动态 Git 状态，固定注入
`git_commit=None`、`git_dirty=None`；普通 CLI/Python run 仍记录能够获得的真实
Git metadata。这样 golden result 不会因为测试发生在不同 commit 上而失效，也
不会伪造 commit。

---

## 11. TraceWriter

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

TraceWriter 是同步 sink：

- record 完成 schema validation 后才可以写入。
- JSONL 使用 UTF-8，每个 object 一行并以 newline 结束。
- 每条 record 写入后立即 flush，不在内存中累计完整 run。
- writer failure 抛 `ComponentExecutionError` 并终止 Agent。
- trace 写入失败后不能继续执行昂贵 action。
- 已成功 flush 的 trace records 保留；Writer 自身失败时，不要求同一个已经损坏的
  Writer 再写一条 terminal record 或 result。
- `result.json` 使用原子目标文件写入；写入失败时不能留下看似完整的结果。
- `write_step` 或 `write_result` 失败时 Python API 传播
  `ComponentExecutionError`，不返回 `AgentRunResult`；CLI 返回 1。
- result 写入失败时，已经成功写入的 terminal trace 可以保留，但 run 不能报告
  为成功。

`resolved_config.json` 不由 Controller/TraceWriter 生成；P1-08 runner 在调用
Controller 前负责保存。Trace/result 仍由 Controller 通过绑定 run directory 的
TraceWriter 写入，CLI 不复制这些写入逻辑。

以上 Writer failure 和 partial-artifact 行为由 P1-09 确认。Replay 对不完整或
缺少 result 的 run 必须明确拒绝，不能把 partial artifacts 当成完整运行。

---

## 12. Replay Definition

正式 replay 是 saved-output replay：

```text
resolved_config.json
+ trace.jsonl
+ result.json
→ schema validation
→ rebuild and validate the recorded state chain
```

Replay 不调用 User Memory、Ranker、Value Model、Perceiver、ScoreUpdater 或其他
Agent component，也不解析大型 ResourceRef 内容。

至少验证：

- 所有 run ID 一致。
- `decision_index` 从 0 连续递增。
- chained before/after State 连续。
- State schema 和跨对象 invariants 成立。
- `action_consumed`、State step 和 Result attempted actions 一致。
- Value outputs 覆盖当时全部 unobserved segments。
- selected value 是确定性 argmax，tie-break 正确。
- succeeded/failed PerceptionResult 与 Evidence/Observation transition 一致。
- StopReason 与 resolved thresholds/budget/no-segment condition 一致。
- Result final State、terminal decision 和 trace count 与 trace 一致。

Replay 不重新计算真实模型 scores；它验证保存的 score/rank coverage、State
invariants 和 transition chain。

Deterministic re-execution 是独立测试：

```text
same resolved config
+ same seed
+ same fixed run ID
+ same fixed test Git metadata
+ deterministic Mock components
→ exact trace/result comparison
```

它不是 replay 的定义，避免未来 replay 意外重新调用真实 MLLM。

---

## 13. Phase 1 Data Boundary

- Phase 1 trace 只使用 synthetic Mock users。
- 不保存原始 user history。
- `user_id` 必须是 fixture/pseudonymous ID。
- ResourceRef 使用逻辑 store/key，不保存本机绝对媒体路径。
- metadata、StopDecision details 和 persisted exception message 不得包含
  secret、API key、完整本地路径或 stack trace。
- TraceWriter 不擅自 hash/修改 State；否则 trace 与 runtime State 不同，无法
  replay。
- 真实用户数据的进一步脱敏策略必须在进入真实数据阶段前单独确认。
