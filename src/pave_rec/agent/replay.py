"""Saved-output replay: validate artifacts and the recorded state chain without components."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from pave_rec.agent.controller import deterministic_best_segment
from pave_rec.bootstrap import EXPECTED_DESCRIPTOR_VALUES
from pave_rec.config import COMPONENT_ROLE_ORDER, Phase1Config
from pave_rec.domain import (
    AgentRunResult,
    AgentStepTrace,
    ObservationStatus,
    RecommendationState,
    StopReason,
)
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ContractError


def _read_required(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ContractError(f"missing or unreadable replay artifact: {path.name}") from exc


def _validate_relative_path(value: str, field_name: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."}:
        raise ContractError(f"resolved {field_name} is not a normalized project-relative path")


def _unobserved_identities(state: RecommendationState) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (candidate.item_id, segment_id)
            for candidate in state.candidates
            for segment_id in candidate.unobserved_segment_ids
        )
    )


def _candidate(state: RecommendationState, item_id: str):
    for candidate in state.candidates:
        if candidate.item_id == item_id:
            return candidate
    raise ContractError(f"replay state is missing candidate {item_id}")


def _validate_transition(
    before: RecommendationState,
    record: AgentStepTrace,
) -> None:
    after = record.state_after
    if after is None:
        return
    if not record.action_consumed:
        raise ContractError("a state transition must consume one perception action")
    if after.step != before.step + 1:
        raise ContractError("state transition must advance step exactly once")
    if after.max_perception_actions != before.max_perception_actions:
        raise ContractError("state transition changed max_perception_actions")
    if {candidate.item_id for candidate in after.candidates} != {
        candidate.item_id for candidate in before.candidates
    }:
        raise ContractError("state transition changed candidate coverage")
    result = record.perception_result
    if result is None:
        raise ContractError("a published action transition requires a PerceptionResult")
    before_candidate = _candidate(before, result.item_id)
    after_candidate = _candidate(after, result.item_id)
    after_observations = {
        observation.segment_id: observation for observation in after_candidate.segment_observations
    }
    observation = after_observations.get(result.segment_id)
    if observation is None or observation.status is not result.status:
        raise ContractError("post-state observation does not match PerceptionResult")
    if observation.last_attempt_step != after.step:
        raise ContractError("observation last_attempt_step does not match post-state step")
    if result.status is ObservationStatus.SUCCEEDED:
        if result.evidence is None or result.evidence.evidence_id not in observation.evidence_ids:
            raise ContractError("successful transition did not publish its Evidence")
        evidence_ids = {entry.evidence_id for entry in after_candidate.evidence.evidence}
        if result.evidence.evidence_id not in evidence_ids:
            raise ContractError("successful transition Evidence is absent from post-state")
    else:
        if after_candidate.evidence != before_candidate.evidence:
            raise ContractError("failed perception must not change Evidence")
        before_scores = {
            candidate.item_id: candidate.current_score for candidate in before.candidates
        }
        after_scores = {
            candidate.item_id: candidate.current_score for candidate in after.candidates
        }
        if before_scores != after_scores:
            raise ContractError("failed perception must not change scores")


def _validate_value_payload(current: RecommendationState, record: AgentStepTrace) -> None:
    if record.segment_values is None:
        return
    expected = _unobserved_identities(current)
    actual = tuple((value.item_id, value.segment_id) for value in record.segment_values)
    if actual != expected:
        raise ContractError("trace SegmentValue coverage/order does not match unobserved segments")
    if not record.segment_values:
        raise ContractError("a persisted SegmentValue batch cannot be empty")
    best = deterministic_best_segment(record.segment_values)
    if record.selected_segment_value != best:
        raise ContractError("selected SegmentValue is not the deterministic argmax")
    if record.selected_segment is None:
        raise ContractError("selected SegmentValue requires selected SegmentMeta")


def _validate_stop_semantics(
    config: Phase1Config,
    current: RecommendationState | None,
    record: AgentStepTrace,
) -> None:
    decision = record.stop_decision
    if decision is None:
        return
    reason = decision.reason
    if reason is StopReason.COMPONENT_FAILURE:
        return
    if reason is StopReason.SAFETY_LIMIT_REACHED:
        if record.action_consumed:
            raise ContractError("safety termination cannot consume an action")
        max_entries = config.agent.max_perception_actions + 1
        if decision.details != {
            "decision_loop_entries": max_entries + 1,
            "max_decision_loop_entries": max_entries,
        }:
            raise ContractError("safety stop details differ from the budget-derived guard")
        return
    if current is None:
        raise ContractError("normal stop reasons require a valid current State")
    if reason is StopReason.BUDGET_EXHAUSTED:
        if current.remaining_perception_actions != 0:
            raise ContractError("budget stop recorded while actions remained")
        expected_details = {
            "max_perception_actions": current.max_perception_actions,
            "remaining_perception_actions": current.remaining_perception_actions,
            "step": current.step,
        }
        if decision.details != expected_details:
            raise ContractError("budget stop details differ from current State")
    elif reason is StopReason.NO_UNOBSERVED_SEGMENTS:
        if _unobserved_identities(current):
            raise ContractError("no-segments stop recorded while segments remained")
        if decision.details["unobserved_segment_count"] != 0:
            raise ContractError("no-segments stop details must record zero segments")
    elif reason is StopReason.RANKING_SUFFICIENTLY_CERTAIN:
        threshold = config.stop.ranking_margin_threshold
        margin = current.ranking_uncertainty.top1_top2_margin
        if threshold is None or margin is None or margin < threshold:
            raise ContractError("certainty stop does not satisfy the resolved threshold")
        if decision.details != {
            "ranking_margin_threshold": threshold,
            "top1_top2_margin": margin,
        }:
            raise ContractError("certainty stop details differ from resolved signals")
    elif reason is StopReason.MAX_SEGMENT_VALUE_TOO_LOW:
        threshold = config.stop.min_segment_value
        if (
            threshold is None
            or record.selected_segment_value is None
            or record.selected_segment_value.value >= threshold
        ):
            raise ContractError("low-value stop does not satisfy the resolved threshold")
        selected = record.selected_segment_value
        if decision.details != {
            "item_id": selected.item_id,
            "segment_id": selected.segment_id,
            "max_segment_value": selected.value,
            "min_segment_value": threshold,
        }:
            raise ContractError("low-value stop details differ from the selected value")


def replay_run(run_dir: str | Path) -> AgentRunResult:
    """Validate all saved artifacts and return the already-recorded final result."""

    directory = Path(run_dir)
    resolved_bytes = _read_required(directory / "resolved_config.json")
    trace_bytes = _read_required(directory / "trace.jsonl")
    result_bytes = _read_required(directory / "result.json")
    try:
        config = Phase1Config.model_validate_json(resolved_bytes)
        result = AgentRunResult.model_validate_json(result_bytes)
    except ValidationError as exc:
        raise ContractError(f"invalid replay artifact schema: {exc}") from exc
    if resolved_bytes != canonical_json_bytes(config, pretty=True):
        raise ContractError("resolved_config.json is not canonical JSON")
    if result_bytes != canonical_json_bytes(result, pretty=True):
        raise ContractError("result.json is not canonical JSON")

    lines = trace_bytes.splitlines(keepends=True)
    if not lines or b"" in lines:
        raise ContractError("trace.jsonl must contain at least one record")
    records: list[AgentStepTrace] = []
    for line in lines:
        if not line.endswith(b"\n") or line.endswith(b"\r\n"):
            raise ContractError("trace.jsonl records must end with exactly LF")
        try:
            record = AgentStepTrace.model_validate_json(line)
        except ValidationError as exc:
            raise ContractError(f"invalid trace record schema: {exc}") from exc
        if line != canonical_json_bytes(record, pretty=False):
            raise ContractError("trace.jsonl contains a non-canonical record")
        records.append(record)

    run_id = config.run.run_id
    if run_id is None or run_id != result.run_id or directory.name != run_id:
        raise ContractError("run directory, resolved config, and result run IDs differ")
    _validate_relative_path(config.run.output_root, "output_root")
    _validate_relative_path(config.input.fixture_path, "fixture_path")
    if result.seed != config.seed or result.data_version != config.data_version:
        raise ContractError("result reproducibility fields differ from resolved config")
    roles = tuple(descriptor.role for descriptor in result.component_descriptors)
    if roles != COMPONENT_ROLE_ORDER:
        raise ContractError("component descriptors are not in fixed role order")
    for descriptor in result.component_descriptors:
        expected_implementation, expected_version = EXPECTED_DESCRIPTOR_VALUES[descriptor.role]
        if (descriptor.implementation, descriptor.version) != (
            expected_implementation,
            expected_version,
        ):
            raise ContractError(f"unexpected persisted descriptor for {descriptor.role}")
    if result.trace_record_count != len(records):
        raise ContractError("result trace_record_count differs from trace.jsonl")

    current: RecommendationState | None = None
    state_seen = False
    consumed_actions = 0
    terminal_decision = None
    for expected_index, record in enumerate(records):
        if record.decision_index != expected_index:
            raise ContractError("trace decision_index must be contiguous from zero")
        if record.run_id != run_id:
            raise ContractError("trace run_id differs from resolved run_id")
        if expected_index == 0:
            current = record.state_before
            state_seen = current is not None
        elif record.state_before is not None:
            raise ContractError("only the first record with State may contain state_before")
        if current is None and record.state_before is None:
            if (
                record.stop_decision is None
                or record.stop_decision.reason is not StopReason.COMPONENT_FAILURE
            ):
                raise ContractError("a stateless trace is only valid for initialization failure")
        elif current is not None:
            _validate_value_payload(current, record)
            _validate_transition(current, record)
        if record.action_consumed:
            consumed_actions += 1

        if record.stop_decision is None:
            if (
                record.information_need is None
                or record.segment_values is None
                or record.selected_segment is None
                or record.selected_segment_value is None
                or record.perception_result is None
                or record.state_after is None
                or not record.action_consumed
            ):
                raise ContractError("completed action trace has an invalid payload shape")
        else:
            if expected_index != len(records) - 1:
                raise ContractError("terminal stop decision must be the final trace record")
            terminal_decision = record.stop_decision
            _validate_stop_semantics(config, current, record)
        if record.state_after is not None:
            current = record.state_after
            state_seen = True

    if not state_seen and result.final_state is not None:
        raise ContractError("stateless initialization failure cannot have final_state")
    if result.final_state != current:
        raise ContractError("result final_state differs from the terminal trace chain")
    if terminal_decision is None or result.stop_decision != terminal_decision:
        raise ContractError("result stop decision differs from terminal trace")
    if result.attempted_perception_actions != consumed_actions:
        raise ContractError("result attempted actions differ from trace accounting")
    expected_success = terminal_decision.reason not in {
        StopReason.COMPONENT_FAILURE,
        StopReason.SAFETY_LIMIT_REACHED,
    }
    if result.succeeded is not expected_success:
        raise ContractError("result succeeded flag disagrees with terminal reason")
    return result
