from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from pave_rec.domain import (
    AgentRunRequest,
    AgentRunResult,
    AgentStepTrace,
    CandidateScore,
    ComponentDescriptor,
    Evidence,
    InitialRankedCandidate,
    InitialRankingOutput,
    ObservationStatus,
    PerceptionResult,
    PreferenceMatchType,
    PreferenceMatchView,
    RankingUncertainty,
    RecommendationStateBuildRequest,
    ResourceRef,
    SegmentMeta,
    SegmentObservationState,
    StopDecision,
    StopReason,
)
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ContractError
from pave_rec.fixture import MockFixture
from pave_rec.recommendation_state.builder import (
    DefaultRecommendationStateBuilder,
    empty_evidence_state,
    empty_observation_state,
)


def _initial_state(fixture: MockFixture):
    candidate_ids = fixture.input.candidate_ids
    scores = tuple(
        CandidateScore(item_id=entry.item_id, score=entry.score)
        for entry in fixture.initial_ranking.candidates
    )
    request = RecommendationStateBuildRequest(
        schema_version="1",
        run_id="mock-v1-golden",
        user_id=fixture.input.user_id,
        user_memory=fixture.user_memory,
        initial_ranking=fixture.initial_ranking,
        current_scores=scores,
        item_feature_refs=fixture.item_feature_refs,
        segment_catalog=fixture.segment_catalog,
        evidence_state=empty_evidence_state(candidate_ids),
        observation_state=empty_observation_state(candidate_ids, fixture.segment_catalog),
        max_perception_actions=2,
        remaining_perception_actions=2,
        step=0,
        metadata={},
    )
    return DefaultRecommendationStateBuilder().build(request)


def test_domain_round_trip_frozen_and_json_copy(mock_fixture: MockFixture) -> None:
    state = _initial_state(mock_fixture)
    encoded = canonical_json_bytes(state, pretty=True)
    assert encoded.endswith(b"\n") and not encoded.startswith(b"\xef\xbb\xbf")
    assert type(state).model_validate_json(encoded) == state
    with pytest.raises(ValidationError):
        state.step = 1

    metadata: dict[str, object] = {"nested": {"value": 1}}
    evidence = Evidence(
        evidence_id="e",
        item_id="item",
        segment_id="segment",
        attributes={},
        text_summary=None,
        confidence=None,
        source="test",
        raw_output_ref=None,
        embedding_ref=None,
        metadata=metadata,
    )
    metadata["nested"]["value"] = 2
    assert evidence.metadata["nested"]["value"] == 1


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ResourceRef(store="", key="k", version="v", checksum=None),
        lambda: SegmentMeta(
            item_id="i",
            segment_id="s",
            start_ms=10,
            end_ms=10,
            media_ref=ResourceRef(store="x", key="k", version="v", checksum=None),
            metadata={},
        ),
        lambda: InitialRankedCandidate(item_id="i", score=math.inf, rank=1),
        lambda: RankingUncertainty(top1_top2_margin=-0.1),
        lambda: PreferenceMatchView(
            long_atom_id=None,
            short_atom_id=None,
            similarity=None,
            classification=PreferenceMatchType.FADING,
        ),
        lambda: AgentRunRequest(run_id="r", user_id="u", user_history=(), candidate_ids=()),
        lambda: AgentRunRequest(run_id="r", user_id="u", user_history=(), candidate_ids=("i", "i")),
    ],
)
def test_invalid_domain_values_are_rejected(factory) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_ranking_and_observation_invariants() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        InitialRankingOutput(
            candidates=(
                InitialRankedCandidate(item_id="a", score=1.0, rank=1),
                InitialRankedCandidate(item_id="b", score=0.0, rank=3),
            ),
            user_sequence_feature_ref=None,
            metadata={},
        )
    with pytest.raises(ValidationError):
        SegmentObservationState(
            item_id="a",
            segment_id="s",
            status=ObservationStatus.UNOBSERVED,
            attempt_count=1,
            evidence_ids=(),
            failure_reason=None,
            last_attempt_step=1,
        )
    with pytest.raises(ValidationError):
        SegmentObservationState(
            item_id="a",
            segment_id="s",
            status=ObservationStatus.FAILED,
            attempt_count=1,
            evidence_ids=(),
            failure_reason=None,
            last_attempt_step=1,
        )


def test_perception_result_contract(mock_fixture: MockFixture) -> None:
    success = mock_fixture.perception_results[0]
    assert success.status is ObservationStatus.SUCCEEDED
    with pytest.raises(ValidationError):
        PerceptionResult(
            item_id="a",
            segment_id="s",
            status=ObservationStatus.UNOBSERVED,
            evidence=None,
            failure_code=None,
            failure_reason=None,
            metadata={},
        )
    with pytest.raises(ValidationError):
        PerceptionResult(
            item_id="a",
            segment_id="s",
            status=ObservationStatus.FAILED,
            evidence=success.evidence,
            failure_code="code",
            failure_reason="reason",
            metadata={},
        )


def test_stop_decision_requires_exact_details() -> None:
    assert StopDecision(stop=False, reason=None, details={}).reason is None
    with pytest.raises(ValidationError):
        StopDecision(stop=True, reason=None, details={})
    with pytest.raises(ValidationError, match="details keys"):
        StopDecision(
            stop=True,
            reason=StopReason.BUDGET_EXHAUSTED,
            details={"step": 0},
        )


def test_state_builder_ranking_tie_break_and_coverage(mock_fixture: MockFixture) -> None:
    candidate_ids = mock_fixture.input.candidate_ids
    tied_scores = tuple(CandidateScore(item_id=item_id, score=1.0) for item_id in candidate_ids)
    request = RecommendationStateBuildRequest(
        schema_version="1",
        run_id="mock-v1-golden",
        user_id=mock_fixture.input.user_id,
        user_memory=mock_fixture.user_memory,
        initial_ranking=mock_fixture.initial_ranking,
        current_scores=tied_scores,
        item_feature_refs=mock_fixture.item_feature_refs,
        segment_catalog=mock_fixture.segment_catalog,
        evidence_state=empty_evidence_state(candidate_ids),
        observation_state=empty_observation_state(candidate_ids, mock_fixture.segment_catalog),
        max_perception_actions=2,
        remaining_perception_actions=2,
        step=0,
        metadata={},
    )
    state = DefaultRecommendationStateBuilder().build(request)
    assert tuple(candidate.item_id for candidate in state.candidates) == candidate_ids
    assert state.ranking_uncertainty.top1_top2_margin == 0.0

    bad = request.model_copy(update={"current_scores": tied_scores[:-1]})
    with pytest.raises(ContractError, match="cover exactly"):
        DefaultRecommendationStateBuilder().build(bad)


def test_trace_and_result_cross_field_validation(repo_root) -> None:
    expected = repo_root / "tests/fixtures/mock/v1/expected"
    trace = AgentStepTrace.model_validate_json(
        (expected / "trace.jsonl").read_bytes().splitlines()[0]
    )
    result = AgentRunResult.model_validate_json((expected / "result.json").read_bytes())

    trace_mutations = (
        {"decision_index": -1},
        {"run_id": "different-run"},
        {
            "selected_segment_value": trace.selected_segment_value.model_copy(
                update={"item_id": "different-item"}
            )
        },
        {
            "perception_result": trace.perception_result.model_copy(
                update={"item_id": "different-item"}
            )
        },
    )
    for mutation in trace_mutations:
        payload = trace.model_dump(mode="python", exclude_none=False)
        payload.update(mutation)
        with pytest.raises(ValidationError):
            AgentStepTrace.model_validate(payload)

    failure_stop = StopDecision(
        stop=True,
        reason=StopReason.COMPONENT_FAILURE,
        details={
            "component_role": "controller",
            "error_type": "ContractError",
            "message": "failure",
        },
    )
    mutations = (
        {"attempted_perception_actions": -1},
        {"trace_record_count": 0},
        {"stop_decision": StopDecision(stop=False, reason=None, details={})},
        {"final_state": None},
        {"stop_decision": failure_stop},
        {"succeeded": False},
        {"git_commit": ""},
        {"final_state": result.final_state.model_copy(update={"run_id": "different-run"})},
        {
            "component_descriptors": (
                result.component_descriptors[0],
                ComponentDescriptor(
                    role=result.component_descriptors[0].role,
                    implementation="DuplicateRole",
                    version="test",
                ),
            )
        },
    )
    for mutation in mutations:
        payload = result.model_dump(mode="python", exclude_none=False)
        payload.update(mutation)
        with pytest.raises(ValidationError):
            AgentRunResult.model_validate(payload)
