# Module 08 — Agent Controller and Stop Policy
# Agent 控制器与停止策略

## 1. 模块目标 Purpose

负责协调完整的 active-perception loop。

`AgentController` 本身不要塞太多研究逻辑。

研究逻辑应该分别放在：

- Information Need Estimator
- Segment Value Model
- Stop Policy
- Score Updater

Controller 只负责 orchestrate。

---

## 2. Controller API

Controller 返回完整运行结果，而不是只返回 final ranking。`AgentRunResult` 的
字段已由 P1-07 确认；P1-08 已确认 run input 使用 strict/frozen
`AgentRunRequest`：

```python
class AgentController:
    def run(
        self,
        request: AgentRunRequest,
    ) -> AgentRunResult:
        ...
```

`AgentRunRequest` 保存 `run_id`、`user_id`、`user_history` 和 `candidate_ids`。
Budget、stop thresholds、seed、data version、components、component descriptors 和
可获得的 Git metadata 在构造 Controller 时注入。空 candidate input、重复
candidate ID 或 run identity 不一致是启动前 `ContractError`，不是一次正常
StopDecision。

`run()` 只有在 terminal trace 和 `result.json` 都成功写入后才返回
`AgentRunResult`。TraceWriter 的 `write_step` 或 `write_result` 失败是 P1-09
确认的 artifact-sink 特殊边界：方法传播 `ComponentExecutionError`，不返回一个
未被完整持久化的 Result。

---

## 3. Confirmed Runtime State Machine

P1-05 已确认正常路径、perception failure 路径和 declared exception 边界。
StopPolicy 签名和 Budget/Stop semantics 已由 P1-06 确认；Trace/Result 的字段
已由 P1-07 确认。所有公共对象以
[`00_shared_domain_schemas.md`](00_shared_domain_schemas.md) 为准，组件调用以
[`00_component_interfaces.md`](00_component_interfaces.md) 为准。

### 3.1 One-time Initialization

以下工作在 loop 外只执行一次：

```text
validate run input
→ build UserMemoryView
→ load static item/segment references
→ compute InitialRankingOutput
→ initialize current scores
→ initialize empty EvidenceState and ObservationState
→ set step=0 and remaining=max actions
→ build step-0 RecommendationState
```

User Memory、Initial Ranker 和静态 Stores 不在每轮重复执行。

### 3.2 Decision Iteration

每轮使用当前已发布的 immutable State：

```text
current RecommendationState
→ pre-value stop check
→ estimate Information Need
→ project all unobserved (item, segment) pairs
→ batch Segment Value prediction
→ deterministic best-value lookup
→ post-value stop check
→ perceive selected segment
→ stage Observation/Evidence transition
→ update scores on success
→ advance action counters
→ rebuild RecommendationState
→ emit completed transition
→ next iteration
```

- pre-value stop 在 Information Need 之前，避免 zero-budget、certainty 或
  no-unobserved 状态继续计算。
- remaining action 为 0 时，pre-value StopPolicy 必须停止。若它错误地返回
  continue，Controller 抛出 `ContractError`，不允许发生超预算 action。
- 没有 unobserved segment 时，pre-value StopPolicy 必须停止。若它错误地返回
  continue，Controller 抛出 `ContractError`，不调用 Value Model。
- 非空 candidate-segment input 的 Value output 必须一一覆盖；empty/missing/
  extra output 是 `ContractError`。
- Value 相同按 `(item_id, segment_id)` 升序打破并列。这只是工程确定性规则。
- Controller 将全部 unobserved segment identities 按 `(item_id, segment_id)`
  升序投影为 `CandidateSegmentRef`；验证 Value identity coverage 后，将 outputs
  归一化到该 input 顺序再用于 trace 和 deterministic argmax。
- post-value stop 在 Perceiver 之前，因此 low-value stop 不消耗 perception
  action。

### 3.3 Counter Semantics

```text
initial State.step = 0
attempt_step = current State.step + 1
next State.step = attempt_step
next remaining = max_perception_actions - next State.step
```

第一次 Perceiver 正常返回后，`last_attempt_step=1` 且新 State 的 `step=1`。
成功和正常 failed result 使用同样的 counter transition。

### 3.4 Conceptual Control Flow

```python
# one-time initialization
user_memory_view = user_memory.build_or_update(user_id, tuple(user_history))
item_feature_refs = item_store.load_refs(tuple(candidate_ids))
segment_catalog = segment_store.load_catalog(tuple(candidate_ids))
initial_ranking = initial_ranker.score(
    user_id,
    tuple(user_history),
    tuple(candidate_ids),
)
scores = scores_from(initial_ranking)
evidence_state = EvidenceState.empty(candidate_ids)
observation_state = ObservationState.empty(candidate_ids, segment_store)
max_perception_actions = config.max_perception_actions
step = 0
state = build_state(...)

while True:
    enforce_safety_guard(...)

    pre_decision = stop_policy.decide_pre_value(state)
    if pre_decision.stop:
        return terminal_result(state, pre_decision)
    if state.remaining_perception_actions == 0:
        raise ContractError("pre-value policy continued without budget")

    need = information_need_estimator.estimate(state)
    segments = candidate_segments_from(state)
    if not segments:
        raise ContractError("pre-value policy continued without segments")

    values = segment_value_model.predict(
        SegmentValueInput(
            state=state,
            information_need=need,
            candidate_segments=segments,
        )
    )
    validate_value_coverage(segments, values)

    best = deterministic_argmax(values)

    post_decision = stop_policy.decide_post_value(
        state,
        best,
    )
    if post_decision.stop:
        return terminal_result(state, post_decision)

    result = perceiver.observe(
        PerceptionRequest(
            segment=find_segment_meta(segment_catalog, best),
            information_need=need,
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
    state = build_state(...)
    emit_completed_transition(...)
```

`candidate_segments_from`、`find_segment_meta` 和 `state_candidate` 表示无研究
逻辑的确定性 projection/lookup，不是额外可插拔 component。伪代码省略了下一节
说明的 terminal error handling。

### 3.5 Normal Perception Failure

`PerceptionResult(status=failed)` 是正常业务结果：

```text
mark selected segment failed
→ do not create Evidence
→ keep scores unchanged
→ advance step and deduct one action
→ rebuild State
→ continue if another action remains possible
```

Failed segment 不自动重试，也不会再次出现在 unobserved projection。

### 3.6 Declared Exceptions and Partial Progress

`ContractError`、`ResourceResolutionError` 和 `ComponentExecutionError` 都会终止
当前 run，不自动继续，也不转换为空输出或伪成功。未声明的编程异常向外传播。

- UserMemory、Item/Segment Store、InitialRanker 或初始 StateBuilder 在 one-time
  initialization 中失败时，不存在合法 State，也不消耗 action。TraceWriter 正常
  时，Controller 写一条无 before/after State 的 component-failure record，并写
  `final_state=None` 的 failed Result。

- ScoreUpdater 失败时，已经成功取得并通过 updater 验证的 Evidence、
  Observation 和本次 action counter 被保留；scores 保持上一版。Controller
  构造一致的 terminal State，并记录 component failure。
- EvidenceUpdater 或 ObservationUpdater 失败时，无法发布满足跨对象 invariant
  的 post-State，因此保留最后一个合法 State；terminal result/trace 单独记录
  已发生的 attempt 和异常。
- 其他业务/运行时 declared exception 同样停止在最后一个合法 State，并在
  TraceWriter 健康时写 terminal trace/result。异常 action accounting 和 terminal
  trace layout 已分别由 P1-06/P1-07 确认；Phase 1 不增加 timing/cost fields。
- TraceWriter 自身的 declared exception 不走“再用 Writer 写 terminal result”的
  一般路径。它立即停止后续 action、保留此前成功 flush 的 records，并向调用方
  传播 `ComponentExecutionError`。

Controller 不发布 Evidence/Observation 不一致的中间 RecommendationState。

---

## 4. Budget and Stop Policy

### 4.1 Action Budget Contract

Phase 1 只有一维 action budget：

```text
max_perception_actions: int >= 0
step: number of consumed perception actions represented by this valid State
remaining_perception_actions = max_perception_actions - step
```

不建立多维 `BudgetState`，不新增 frame/token/latency/cost placeholder schema。
这些真实 MLLM telemetry 留到对应模型阶段讨论，不进入 Phase 1 Stop Policy。

budget 为 0 时仍完成 cheap/static initialization 并构造 step-0 State，然后以
`budget_exhausted` 停止；不调用 Information Need、Value Model 或 Perceiver。

Controller 以调用 `SegmentPerceiver.observe()` 为 action 消费边界：

- succeeded result 消耗一次。
- failed result 消耗一次。
- Perceiver declared exception 也记录一次已发起 action。
- pre/post stop 和 Perceiver 调用前的 exception 不消耗。
- Evidence/Observation/ScoreUpdater exception 不额外重复消耗。

异常导致无法发布 post-State 时，最后一个合法 State 可以保留旧 step；P1-07
的 terminal Trace/Result 必须记录本次已经消耗的 action，不能伪造不合法 State。

### 4.2 StopReason

Phase 1 使用固定 enum：

```text
budget_exhausted
ranking_sufficiently_certain
no_unobserved_segments
max_segment_value_too_low
component_failure
safety_limit_reached
```

空或重复 candidate input 是启动前 `ContractError`，不是正常 StopReason。

### 4.3 StopPolicy Interface

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

pre-value 按以下顺序检查：

```text
remaining actions == 0
→ budget_exhausted

no unobserved segments
→ no_unobserved_segments

margin threshold enabled and margin >= threshold
→ ranking_sufficiently_certain
```

`top1_top2_margin=None` 时跳过 certainty condition，不报错，也不自动判定为确定。

post-value 检查：

```text
minimum value threshold enabled
AND best_segment_value.value < threshold
→ max_segment_value_too_low
```

阈值等于 `None` 表示关闭对应可选条件。Budget、no-unobserved、component failure
和 safety guard 不能通过配置关闭。

### 4.4 Stop Priority

整体 terminal priority 为：

```text
safety_limit_reached
> component_failure
> budget_exhausted
> no_unobserved_segments
> ranking_sufficiently_certain
> max_segment_value_too_low
```

Safety/component failure 是 Controller 即时 terminal path；后四项通过已确认的
pre/post-value control flow 自然排序。正常 failed perception 本身不是
StopReason；提交 failed State 后由下一轮条件决定是否停止。

### 4.5 StopDecision Contract

公共返回对象：

```python
class StopDecision:
    stop: bool
    reason: StopReason | None
    details: JsonObject
```

- continue：`stop=False`、`reason=None`、`details={}`。
- terminal：`stop=True`、reason 必须存在。
- details 只保存结构化诊断信号，不用于替代 enum 或驱动隐藏控制逻辑。
- Phase 1 terminal details 使用以下精确 key contract，不增加同义或隐藏控制字段：

```text
budget_exhausted:
  max_perception_actions, remaining_perception_actions, step

no_unobserved_segments:
  unobserved_segment_count

ranking_sufficiently_certain:
  ranking_margin_threshold, top1_top2_margin

max_segment_value_too_low:
  item_id, segment_id, max_segment_value, min_segment_value

component_failure:
  component_role, error_type, message

safety_limit_reached:
  decision_loop_entries, max_decision_loop_entries
```

`component_role` 使用稳定 config role，Controller 自身的 contract/safety helper
使用 `controller`；`error_type` 使用稳定 exception class name；`message` 必须简洁
且经过边界清理，不能包含 secret、stack trace 或本机绝对路径。JSON serializer
负责 key 排序，因此上述列举顺序不承担字节顺序语义。

Phase 1 不增加 cancellation token 或 `external_cancelled` reason。同步 CLI 的
interrupt 交给进程入口处理；未来 async/service runtime 再单独讨论。

---

## 5. Trace Logging

逻辑写入时机已确认：

- 正常 action 在 post-State 成功重建后提交 completed transition。
- pre-value/post-value stop 提交 terminal outcome。
- 业务/运行时 declared component exception 在 TraceWriter 健康时提交 terminal
  failure；TraceWriter 自身 failure 传播而不递归记录。

`AgentStepTrace` 是 strict、frozen、JSON-serializable 公共对象。P1-07 已确认
每次 decision-loop 写一条 JSONL；State 使用链式保存避免相邻重复，正常
transition rebuild 后写入，terminal branch 写最后一条 stop/failure record。

权威 Schema、run-directory 和 replay 规则见
[`00_trace_replay.md`](00_trace_replay.md)。

---

## 6. Safety Guard

Controller 必须有独立于 learned/Mock policy 的 hard loop guard。Phase 1 从
`max_perception_actions` 推导最多
`max_perception_actions + 1` 次 decision-loop 进入：最多 N 次 action，加一次
最终 pre-value stop check，不增加另一套研究配置。触发 guard 后必须终止；
StopReason 固定为 `safety_limit_reached`。

---

## 7. Reproducibility

P1-07/P1-08 已确认每次 run 的可复现信息分布如下：

- `resolved_config.json`：完整 typed config、实际 run ID、seed、data/fixture version
  和 component implementation selections。
- `trace.jsonl`：决策链和完整 State snapshots；State 包含 fixture/pseudonymous
  user ID 和 candidate IDs。
- `result.json`：seed、data version、component descriptors、Git metadata、final
  State 和 terminal decision。
- 真实 checkpoint、feature 或 media 不内嵌；需要时通过 versioned `ResourceRef`
  关联。

---

## 8. V1

第一版可以使用：

```text
mock user memory
mock initial ranker
mock information need
mock value model
mock perceiver
mock score updater
configurable Phase 1 stop policy
```

主要目标是先验证 loop。
Phase 1 的固定输入、两步预期运行和各 Mock component 查表映射见
[`00_deterministic_mock_scenario.md`](00_deterministic_mock_scenario.md)。

---

## 9. Phase 3 Real Cheap Path Integration

P3-07 keeps `AgentController` and all public component protocols unchanged. The
first real integration injects an immutable `ArtifactUserMemory`, a dataset-specific
`SasrecInitialRanker`, and the existing persistent filesystem Item/Segment Stores.
The exact P2 release, P3 derived/semantic/checkpoint/Memory artifacts and fixed
`AgentInputBundle` are validated before Controller construction.

The bundle's one public history tuple is the complete, untruncated `positive_v1`
item-ID projection before its exact cutoff. Bootstrap separately validates the
full-exposure cutoff and binds the exact Memory snapshot; `ArtifactUserMemory` only
validates the tuple fingerprint, while SASRec applies OOV filtering and recent-50
internally. The tuple is never used to guess a Memory snapshot, and no second history
field is added to `AgentRunRequest`.

```text
exact Memory snapshot + SASRec checkpoint + persistent Stores
        ↓
unchanged AgentController builds Recommendation State
        ↓
max_perception_actions = 0
        ↓
pre-value StopPolicy returns budget_exhausted
```

Phase 4/5 roles use explicit unavailable guards rather than Mock outputs. Runtime
config validation requires zero budget while any guard is selected, and an accidental
guard call is a declared component failure. This proves the real Cheap Path without
executing or claiming a real Information Need, Segment Value, Perceiver, or Score
Updater.

The real runner preflights the closed exact artifact graph, request prefix/candidate
coverage and device before allocating a formal run directory. A successful smoke
still writes exactly `resolved_config.json`, `trace.jsonl`, and `result.json`; model,
Memory and dataset payloads remain external behind versioned references. P3 resolved
config/result metadata record exact portable refs without physical paths or secrets,
and trace/state schemas do not change. Structural replay recognizes the P3 resolved
config discriminator but does not load tensors or re-execute components. Existing
Phase 1 mock configs, descriptors, golden artifacts and replay behavior remain
unchanged.

The first exact real run is `runs/phase3/20260804T141855Z-40d12921`. It consumed
the pinned P2/derived/semantic/SASRec/Memory/input artifact graph, built a real
101-candidate Recommendation State, attempted zero perception actions, wrote one
terminal trace record, and stopped successfully with `budget_exhausted`. The same
directory passes discriminator-aware saved-output replay without loading tensors or
re-executing the Controller:

```text
python -m pave_rec.cli.phase3 run --config configs/phase3/runtime_zero_budget.yaml
python -m pave_rec.cli.phase3 replay --run-dir runs/phase3/20260804T141855Z-40d12921
```

---

## 10. TBD

- whether stop is predicted by a learned policy
- whether segment selection and stop become a unified action space
- whether RL later controls the entire loop
