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

- ScoreUpdater 失败时，已经成功取得并通过 updater 验证的 Evidence、
  Observation 和本次 action counter 被保留；scores 保持上一版。Controller
  构造一致的 terminal State，并记录 component failure。
- EvidenceUpdater 或 ObservationUpdater 失败时，无法发布满足跨对象 invariant
  的 post-State，因此保留最后一个合法 State；terminal result/trace 单独记录
  已发生的 attempt 和异常。
- 其他 declared exception 同样停止在最后一个合法 State。异常 action accounting
  和 terminal trace layout 已分别由 P1-06/P1-07 确认；Phase 1 不增加
  timing/cost fields。

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

- continue：`stop=False`、`reason=None`。
- terminal：`stop=True`、reason 必须存在。
- details 只保存结构化诊断信号，不用于替代 enum 或驱动隐藏控制逻辑。
- terminal details 至少记录相应的 budget counters、margin/threshold、
  unobserved count、best segment/value/threshold、component role/error type 或
  safety iterations/limit。

Phase 1 不增加 cancellation token 或 `external_cancelled` reason。同步 CLI 的
interrupt 交给进程入口处理；未来 async/service runtime 再单独讨论。

---

## 5. Trace Logging

逻辑写入时机已确认：

- 正常 action 在 post-State 成功重建后提交 completed transition。
- pre-value/post-value stop 提交 terminal outcome。
- declared component exception 提交 terminal failure。

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

## 9. TBD

- whether stop is predicted by a learned policy
- whether segment selection and stop become a unified action space
- whether RL later controls the entire loop
