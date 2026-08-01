"""Phase 1 controller implementing the confirmed immutable agent state machine."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from pave_rec.agent.base import StopPolicy, TraceWriter
from pave_rec.agent.stop import safety_decision
from pave_rec.domain import (
    AgentRunRequest,
    AgentRunResult,
    AgentStepTrace,
    CandidateScore,
    CandidateSegmentRef,
    ComponentDescriptor,
    EvidenceState,
    InformationNeed,
    InitialRankingOutput,
    ItemFeatureRef,
    ItemSegmentCatalog,
    ObservationState,
    ObservationStatus,
    PerceptionRequest,
    PerceptionResult,
    RecommendationState,
    RecommendationStateBuildRequest,
    ScoreUpdateRequest,
    SegmentMeta,
    SegmentValue,
    SegmentValueInput,
    StopDecision,
    StopReason,
)
from pave_rec.errors import ContractError, PaveRecError
from pave_rec.information_need.base import InformationNeedEstimator
from pave_rec.perception.base import SegmentPerceiver
from pave_rec.ranking.initial.base import InitialRanker
from pave_rec.ranking.update.base import ScoreUpdater
from pave_rec.recommendation_state.base import (
    EvidenceUpdater,
    ObservationUpdater,
    RecommendationStateBuilder,
)
from pave_rec.recommendation_state.builder import empty_evidence_state, empty_observation_state
from pave_rec.segment_value.base import SegmentValueModel
from pave_rec.stores.base import ItemFeatureStore, SegmentStore
from pave_rec.user_memory.base import UserMemory

T = TypeVar("T")
SegmentIdentity = tuple[str, str]


@dataclass(frozen=True)
class AgentComponents:
    user_memory: UserMemory
    initial_ranker: InitialRanker
    item_feature_store: ItemFeatureStore
    segment_store: SegmentStore
    state_builder: RecommendationStateBuilder
    information_need: InformationNeedEstimator
    segment_value: SegmentValueModel
    perceiver: SegmentPerceiver
    evidence_updater: EvidenceUpdater
    observation_updater: ObservationUpdater
    score_updater: ScoreUpdater
    stop_policy: StopPolicy
    trace_writer: TraceWriter


@dataclass(frozen=True)
class _DeclaredFailure(Exception):
    role: str
    error: PaveRecError


def _call(role: str, operation: Callable[..., T], *args: object, **kwargs: object) -> T:
    try:
        return operation(*args, **kwargs)
    except PaveRecError as exc:
        raise _DeclaredFailure(role=role, error=exc) from exc


def _contract_failure(role: str, message: str) -> _DeclaredFailure:
    return _DeclaredFailure(role=role, error=ContractError(message))


def _sanitize_message(error: PaveRecError) -> str:
    message = " ".join(str(error).split()) or type(error).__name__
    message = re.sub(r"[A-Za-z]:[\\/][^\s]+", "<path>", message)
    message = re.sub(r"(?<!\w)/(?:[^/\s]+/)+[^\s]+", "<path>", message)
    return message[:500]


def normalize_segment_values(
    candidate_segments: tuple[CandidateSegmentRef, ...],
    values: tuple[SegmentValue, ...],
) -> tuple[SegmentValue, ...]:
    expected = tuple((entry.item_id, entry.segment_id) for entry in candidate_segments)
    actual = tuple((entry.item_id, entry.segment_id) for entry in values)
    if len(actual) != len(set(actual)):
        raise ContractError("segment-value output contains duplicate identities")
    if set(actual) != set(expected):
        missing = sorted(set(expected).difference(actual))
        extra = sorted(set(actual).difference(expected))
        raise ContractError(f"segment-value coverage mismatch; missing={missing}, extra={extra}")
    indexed = {(entry.item_id, entry.segment_id): entry for entry in values}
    return tuple(indexed[identity] for identity in expected)


def deterministic_best_segment(values: tuple[SegmentValue, ...]) -> SegmentValue:
    if not values:
        raise ContractError("cannot select a segment from an empty value batch")
    return min(values, key=lambda entry: (-entry.value, entry.item_id, entry.segment_id))


def project_candidate_segments(
    state: RecommendationState,
) -> tuple[CandidateSegmentRef, ...]:
    projected: list[CandidateSegmentRef] = []
    for candidate in state.candidates:
        proxies = {entry.segment_id: entry.feature_ref for entry in candidate.segment_proxy_refs}
        for segment_id in candidate.unobserved_segment_ids:
            if segment_id not in proxies:
                raise ContractError(
                    f"missing proxy for unobserved segment {candidate.item_id}/{segment_id}"
                )
            projected.append(
                CandidateSegmentRef(
                    item_id=candidate.item_id,
                    segment_id=segment_id,
                    item_feature_ref=candidate.item_feature_ref,
                    segment_proxy_ref=proxies[segment_id],
                )
            )
    return tuple(sorted(projected, key=lambda entry: (entry.item_id, entry.segment_id)))


def _validate_item_coverage(
    expected_ids: tuple[str, ...], entries: tuple[object, ...], *, role: str
) -> None:
    actual_ids = tuple(getattr(entry, "item_id", None) for entry in entries)
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected_ids):
        raise _contract_failure(role, "component output does not cover exactly the requested items")


class AgentController:
    def __init__(
        self,
        *,
        expected_run_id: str,
        components: AgentComponents,
        max_perception_actions: int,
        seed: int,
        data_version: str,
        component_descriptors: tuple[ComponentDescriptor, ...],
        git_commit: str | None,
        git_dirty: bool | None,
        result_metadata: dict[str, object] | None = None,
        schema_version: str = "1",
    ) -> None:
        self._expected_run_id = expected_run_id
        self._components = components
        self._max_perception_actions = max_perception_actions
        self._seed = seed
        self._data_version = data_version
        self._component_descriptors = component_descriptors
        self._git_commit = git_commit
        self._git_dirty = git_dirty
        self._result_metadata = result_metadata or {}
        self._schema_version = schema_version

    def _build_state(
        self,
        *,
        request: AgentRunRequest,
        user_memory: object,
        initial_ranking: InitialRankingOutput,
        scores: tuple[CandidateScore, ...],
        item_feature_refs: tuple[ItemFeatureRef, ...],
        segment_catalog: tuple[ItemSegmentCatalog, ...],
        evidence_state: EvidenceState,
        observation_state: ObservationState,
        step: int,
    ) -> RecommendationState:
        build_request = RecommendationStateBuildRequest(
            schema_version=self._schema_version,
            run_id=request.run_id,
            user_id=request.user_id,
            user_memory=user_memory,
            initial_ranking=initial_ranking,
            current_scores=scores,
            item_feature_refs=item_feature_refs,
            segment_catalog=segment_catalog,
            evidence_state=evidence_state,
            observation_state=observation_state,
            max_perception_actions=self._max_perception_actions,
            remaining_perception_actions=self._max_perception_actions - step,
            step=step,
            metadata={},
        )
        return _call("state_builder", self._components.state_builder.build, build_request)

    def _write_terminal(
        self,
        *,
        request: AgentRunRequest,
        decision_index: int,
        trace_count: int,
        state_recorded: bool,
        current_state: RecommendationState | None,
        final_state: RecommendationState | None,
        information_need: InformationNeed | None,
        segment_values: tuple[SegmentValue, ...] | None,
        selected_segment: SegmentMeta | None,
        selected_value: SegmentValue | None,
        perception_result: PerceptionResult | None,
        action_consumed: bool,
        stop_decision: StopDecision,
        attempted_actions: int,
    ) -> AgentRunResult:
        record = AgentStepTrace(
            schema_version=self._schema_version,
            run_id=request.run_id,
            decision_index=decision_index,
            state_before=current_state
            if current_state is not None and not state_recorded
            else None,
            information_need=information_need,
            segment_values=segment_values,
            selected_segment=selected_segment,
            selected_segment_value=selected_value,
            perception_result=perception_result,
            state_after=final_state if final_state is not current_state else None,
            action_consumed=action_consumed,
            stop_decision=stop_decision,
            metadata={},
        )
        self._components.trace_writer.write_step(record)
        trace_count += 1
        persisted_final_state = final_state if final_state is not None else current_state
        succeeded = stop_decision.reason not in {
            StopReason.COMPONENT_FAILURE,
            StopReason.SAFETY_LIMIT_REACHED,
        }
        result = AgentRunResult(
            schema_version=self._schema_version,
            run_id=request.run_id,
            succeeded=succeeded,
            final_state=persisted_final_state,
            stop_decision=stop_decision,
            attempted_perception_actions=attempted_actions,
            trace_record_count=trace_count,
            seed=self._seed,
            data_version=self._data_version,
            component_descriptors=self._component_descriptors,
            git_commit=self._git_commit,
            git_dirty=self._git_dirty,
            metadata=self._result_metadata,
        )
        self._components.trace_writer.write_result(result)
        return result

    def _write_component_failure(
        self,
        *,
        failure: _DeclaredFailure,
        request: AgentRunRequest,
        decision_index: int,
        trace_count: int,
        state_recorded: bool,
        current_state: RecommendationState | None,
        partial_state: RecommendationState | None,
        information_need: InformationNeed | None,
        segment_values: tuple[SegmentValue, ...] | None,
        selected_segment: SegmentMeta | None,
        selected_value: SegmentValue | None,
        perception_result: PerceptionResult | None,
        action_consumed: bool,
        attempted_actions: int,
    ) -> AgentRunResult:
        decision = StopDecision(
            stop=True,
            reason=StopReason.COMPONENT_FAILURE,
            details={
                "component_role": failure.role,
                "error_type": type(failure.error).__name__,
                "message": _sanitize_message(failure.error),
            },
        )
        return self._write_terminal(
            request=request,
            decision_index=decision_index,
            trace_count=trace_count,
            state_recorded=state_recorded,
            current_state=current_state,
            final_state=partial_state,
            information_need=information_need,
            segment_values=segment_values,
            selected_segment=selected_segment,
            selected_value=selected_value,
            perception_result=perception_result,
            action_consumed=action_consumed,
            stop_decision=decision,
            attempted_actions=attempted_actions,
        )

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        if request.run_id != self._expected_run_id:
            raise ContractError("AgentRunRequest.run_id does not match the resolved run ID")

        try:
            user_memory = _call(
                "user_memory",
                self._components.user_memory.build_or_update,
                request.user_id,
                request.user_history,
            )
            item_feature_refs = _call(
                "item_feature_store",
                self._components.item_feature_store.load_refs,
                request.candidate_ids,
            )
            _validate_item_coverage(
                request.candidate_ids, item_feature_refs, role="item_feature_store"
            )
            if tuple(entry.item_id for entry in item_feature_refs) != request.candidate_ids:
                raise _contract_failure(
                    "item_feature_store", "item feature output order must match request order"
                )
            segment_catalog = _call(
                "segment_store",
                self._components.segment_store.load_catalog,
                request.candidate_ids,
            )
            _validate_item_coverage(request.candidate_ids, segment_catalog, role="segment_store")
            if tuple(entry.item_id for entry in segment_catalog) != request.candidate_ids:
                raise _contract_failure(
                    "segment_store", "segment catalog output order must match request order"
                )
            initial_ranking = _call(
                "initial_ranker",
                self._components.initial_ranker.score,
                request.user_id,
                request.user_history,
                request.candidate_ids,
            )
            _validate_item_coverage(
                request.candidate_ids, initial_ranking.candidates, role="initial_ranker"
            )
            scores = tuple(
                CandidateScore(item_id=entry.item_id, score=entry.score)
                for entry in initial_ranking.candidates
            )
            evidence_state = empty_evidence_state(request.candidate_ids)
            observation_state = empty_observation_state(request.candidate_ids, segment_catalog)
            state = self._build_state(
                request=request,
                user_memory=user_memory,
                initial_ranking=initial_ranking,
                scores=scores,
                item_feature_refs=item_feature_refs,
                segment_catalog=segment_catalog,
                evidence_state=evidence_state,
                observation_state=observation_state,
                step=0,
            )
        except _DeclaredFailure as failure:
            return self._write_component_failure(
                failure=failure,
                request=request,
                decision_index=0,
                trace_count=0,
                state_recorded=False,
                current_state=None,
                partial_state=None,
                information_need=None,
                segment_values=None,
                selected_segment=None,
                selected_value=None,
                perception_result=None,
                action_consumed=False,
                attempted_actions=0,
            )

        decision_index = 0
        trace_count = 0
        attempted_actions = 0
        state_recorded = False
        loop_entries = 0
        max_loop_entries = self._max_perception_actions + 1

        while True:
            loop_entries += 1
            guard_decision = safety_decision(
                decision_loop_entries=loop_entries,
                max_decision_loop_entries=max_loop_entries,
            )
            if guard_decision is not None:
                return self._write_terminal(
                    request=request,
                    decision_index=decision_index,
                    trace_count=trace_count,
                    state_recorded=state_recorded,
                    current_state=state,
                    final_state=state,
                    information_need=None,
                    segment_values=None,
                    selected_segment=None,
                    selected_value=None,
                    perception_result=None,
                    action_consumed=False,
                    stop_decision=guard_decision,
                    attempted_actions=attempted_actions,
                )

            need: InformationNeed | None = None
            values: tuple[SegmentValue, ...] | None = None
            selected_value: SegmentValue | None = None
            selected_segment: SegmentMeta | None = None
            perception_result: PerceptionResult | None = None
            action_consumed = False
            next_observation_state: ObservationState | None = None
            next_evidence_state: EvidenceState | None = None
            try:
                pre_decision = _call(
                    "stop_policy", self._components.stop_policy.decide_pre_value, state
                )
                if pre_decision.stop:
                    if pre_decision.reason not in {
                        StopReason.BUDGET_EXHAUSTED,
                        StopReason.NO_UNOBSERVED_SEGMENTS,
                        StopReason.RANKING_SUFFICIENTLY_CERTAIN,
                    }:
                        raise _contract_failure(
                            "stop_policy", "pre-value policy returned an invalid stop reason"
                        )
                    return self._write_terminal(
                        request=request,
                        decision_index=decision_index,
                        trace_count=trace_count,
                        state_recorded=state_recorded,
                        current_state=state,
                        final_state=state,
                        information_need=None,
                        segment_values=None,
                        selected_segment=None,
                        selected_value=None,
                        perception_result=None,
                        action_consumed=False,
                        stop_decision=pre_decision,
                        attempted_actions=attempted_actions,
                    )
                if state.remaining_perception_actions == 0:
                    raise _contract_failure(
                        "controller", "pre-value policy continued without budget"
                    )

                need = _call(
                    "information_need",
                    self._components.information_need.estimate,
                    state,
                )
                candidate_segments = _call("controller", project_candidate_segments, state)
                if not candidate_segments:
                    raise _contract_failure(
                        "controller", "pre-value policy continued without unobserved segments"
                    )
                value_request = SegmentValueInput(
                    state=state,
                    information_need=need,
                    candidate_segments=candidate_segments,
                )
                raw_values = _call(
                    "segment_value", self._components.segment_value.predict, value_request
                )
                values = _call(
                    "segment_value",
                    normalize_segment_values,
                    candidate_segments,
                    raw_values,
                )
                selected_value = _call("controller", deterministic_best_segment, values)
                post_decision = _call(
                    "stop_policy",
                    self._components.stop_policy.decide_post_value,
                    state,
                    selected_value,
                )
                if post_decision.stop:
                    if post_decision.reason is not StopReason.MAX_SEGMENT_VALUE_TOO_LOW:
                        raise _contract_failure(
                            "stop_policy", "post-value policy returned an invalid stop reason"
                        )
                    selected_segment = _call(
                        "controller", self._find_segment, segment_catalog, selected_value
                    )
                    return self._write_terminal(
                        request=request,
                        decision_index=decision_index,
                        trace_count=trace_count,
                        state_recorded=state_recorded,
                        current_state=state,
                        final_state=state,
                        information_need=need,
                        segment_values=values,
                        selected_segment=selected_segment,
                        selected_value=selected_value,
                        perception_result=None,
                        action_consumed=False,
                        stop_decision=post_decision,
                        attempted_actions=attempted_actions,
                    )

                selected_segment = _call(
                    "controller", self._find_segment, segment_catalog, selected_value
                )
                selected_candidate = _call(
                    "controller", self._candidate, state, selected_value.item_id
                )
                action_consumed = True
                attempted_actions += 1
                perception_request = PerceptionRequest(
                    segment=selected_segment,
                    information_need=need,
                    user_memory=user_memory,
                    current_item_evidence=selected_candidate.evidence,
                    metadata={},
                )
                perception_result = _call(
                    "perceiver", self._components.perceiver.observe, perception_request
                )
                if (perception_result.item_id, perception_result.segment_id) != (
                    selected_value.item_id,
                    selected_value.segment_id,
                ):
                    raise _contract_failure(
                        "perceiver", "perception result identity does not match selection"
                    )
                attempt_step = state.step + 1
                next_observation_state = _call(
                    "observation_updater",
                    self._components.observation_updater.update,
                    observation_state,
                    perception_result,
                    attempt_step,
                )
                next_evidence_state = evidence_state
                next_scores = scores
                if perception_result.status is ObservationStatus.SUCCEEDED:
                    if perception_result.evidence is None:
                        raise _contract_failure(
                            "perceiver", "successful perception result is missing Evidence"
                        )
                    next_evidence_state = _call(
                        "evidence_updater",
                        self._components.evidence_updater.update,
                        evidence_state,
                        perception_result.evidence,
                    )
                    score_request = ScoreUpdateRequest(
                        user_memory=user_memory,
                        initial_ranking=initial_ranking,
                        previous_scores=scores,
                        item_feature_refs=item_feature_refs,
                        evidence_state=next_evidence_state,
                        metadata={},
                    )
                    next_scores = _call(
                        "score_updater",
                        self._components.score_updater.update,
                        score_request,
                    )
                    _validate_item_coverage(
                        request.candidate_ids, next_scores, role="score_updater"
                    )
                next_state = self._build_state(
                    request=request,
                    user_memory=user_memory,
                    initial_ranking=initial_ranking,
                    scores=next_scores,
                    item_feature_refs=item_feature_refs,
                    segment_catalog=segment_catalog,
                    evidence_state=next_evidence_state,
                    observation_state=next_observation_state,
                    step=attempt_step,
                )
            except _DeclaredFailure as failure:
                partial_state = None
                if (
                    failure.role == "score_updater"
                    and next_observation_state is not None
                    and next_evidence_state is not None
                ):
                    try:
                        partial_state = self._build_state(
                            request=request,
                            user_memory=user_memory,
                            initial_ranking=initial_ranking,
                            scores=scores,
                            item_feature_refs=item_feature_refs,
                            segment_catalog=segment_catalog,
                            evidence_state=next_evidence_state,
                            observation_state=next_observation_state,
                            step=state.step + 1,
                        )
                    except _DeclaredFailure:
                        partial_state = None
                return self._write_component_failure(
                    failure=failure,
                    request=request,
                    decision_index=decision_index,
                    trace_count=trace_count,
                    state_recorded=state_recorded,
                    current_state=state,
                    partial_state=partial_state,
                    information_need=need,
                    segment_values=values,
                    selected_segment=selected_segment,
                    selected_value=selected_value,
                    perception_result=perception_result,
                    action_consumed=action_consumed,
                    attempted_actions=attempted_actions,
                )

            record = AgentStepTrace(
                schema_version=self._schema_version,
                run_id=request.run_id,
                decision_index=decision_index,
                state_before=state if not state_recorded else None,
                information_need=need,
                segment_values=values,
                selected_segment=selected_segment,
                selected_segment_value=selected_value,
                perception_result=perception_result,
                state_after=next_state,
                action_consumed=True,
                stop_decision=None,
                metadata={},
            )
            self._components.trace_writer.write_step(record)
            trace_count += 1
            state_recorded = True
            decision_index += 1
            state = next_state
            observation_state = next_observation_state
            evidence_state = next_evidence_state
            scores = next_scores

    @staticmethod
    def _candidate(state: RecommendationState, item_id: str):
        for candidate in state.candidates:
            if candidate.item_id == item_id:
                return candidate
        raise ContractError(f"state does not contain selected item: {item_id}")

    @staticmethod
    def _find_segment(
        catalog: tuple[ItemSegmentCatalog, ...], selected: SegmentValue
    ) -> SegmentMeta:
        for item in catalog:
            for segment in item.segments:
                if (segment.item_id, segment.segment_id) == (
                    selected.item_id,
                    selected.segment_id,
                ):
                    return segment
        raise ContractError(
            f"selected segment is missing from catalog: {selected.item_id}/{selected.segment_id}"
        )
