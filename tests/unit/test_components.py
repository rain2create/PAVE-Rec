from __future__ import annotations

import pytest

from pave_rec.agent.controller import (
    deterministic_best_segment,
    normalize_segment_values,
    project_candidate_segments,
)
from pave_rec.agent.stop import ThresholdStopPolicy, safety_decision
from pave_rec.domain import (
    CandidateScore,
    CandidateSegmentRef,
    ObservationStatus,
    PerceptionRequest,
    PerceptionResult,
    ScoreUpdateRequest,
    SegmentValue,
    SegmentValueInput,
    StopReason,
)
from pave_rec.errors import ComponentExecutionError, ContractError
from pave_rec.fixture import MockFixture
from pave_rec.information_need.mock import MockInformationNeedEstimator
from pave_rec.perception.mock import MockPerceiver
from pave_rec.ranking.initial.mock import MockInitialRanker
from pave_rec.ranking.update.mock import MockScoreUpdater
from pave_rec.recommendation_state.builder import (
    empty_evidence_state,
    empty_observation_state,
)
from pave_rec.recommendation_state.updaters import (
    MockEvidenceUpdater,
    MockObservationUpdater,
)
from pave_rec.segment_value.mock import MockSegmentValueModel
from pave_rec.stores.in_memory import InMemoryItemFeatureStore, InMemorySegmentStore
from pave_rec.user_memory.mock import MockUserMemory


def test_fixture_components_reject_unknown_keys(mock_fixture: MockFixture) -> None:
    memory = MockUserMemory(mock_fixture)
    ranker = MockInitialRanker(mock_fixture)
    with pytest.raises(ContractError):
        memory.build_or_update("unknown", ())
    with pytest.raises(ContractError):
        ranker.score("unknown", (), ("item_a",))
    with pytest.raises(ContractError):
        InMemoryItemFeatureStore(mock_fixture.item_feature_refs).load_refs(("unknown",))
    with pytest.raises(ContractError):
        InMemorySegmentStore(mock_fixture.segment_catalog).load_catalog(("unknown",))


def test_information_need_and_segment_value_batch(mock_fixture: MockFixture, initial_state) -> None:
    need = MockInformationNeedEstimator(mock_fixture).estimate(initial_state)
    segments = project_candidate_segments(initial_state)
    assert tuple((entry.item_id, entry.segment_id) for entry in segments) == tuple(
        sorted((value.item_id, value.segment_id) for value in mock_fixture.segment_values)
    )
    request = SegmentValueInput(
        state=initial_state,
        information_need=need,
        candidate_segments=segments,
    )
    values = MockSegmentValueModel(mock_fixture.segment_values).predict(request)
    assert deterministic_best_segment(values).item_id == "item_b"
    empty = SegmentValueInput(
        state=initial_state,
        information_need=need,
        candidate_segments=(),
    )
    assert MockSegmentValueModel(mock_fixture.segment_values).predict(empty) == ()
    unknown = CandidateSegmentRef(
        item_id="item_z",
        segment_id="segment_1",
        item_feature_ref=None,
        segment_proxy_ref=None,
    )
    with pytest.raises(ContractError):
        MockSegmentValueModel(mock_fixture.segment_values).predict(
            SegmentValueInput(
                state=initial_state,
                information_need=need,
                candidate_segments=(unknown,),
            )
        )


def test_value_coverage_and_tie_break() -> None:
    refs = (
        CandidateSegmentRef(
            item_id="a",
            segment_id="same",
            item_feature_ref=None,
            segment_proxy_ref=None,
        ),
        CandidateSegmentRef(
            item_id="b",
            segment_id="same",
            item_feature_ref=None,
            segment_proxy_ref=None,
        ),
    )
    values = (
        SegmentValue(item_id="b", segment_id="same", value=1.0, metadata={}),
        SegmentValue(item_id="a", segment_id="same", value=1.0, metadata={}),
    )
    normalized = normalize_segment_values(refs, values)
    assert tuple(value.item_id for value in normalized) == ("a", "b")
    assert deterministic_best_segment(normalized).item_id == "a"
    with pytest.raises(ContractError, match="coverage"):
        normalize_segment_values(refs, values[:1])
    with pytest.raises(ContractError, match="duplicate"):
        normalize_segment_values(refs, (values[0], values[0]))
    with pytest.raises(ContractError, match="empty"):
        deterministic_best_segment(())


def test_perceiver_and_pure_updaters(mock_fixture: MockFixture, initial_state) -> None:
    selected = mock_fixture.segment_catalog[1].segments[0]
    request = PerceptionRequest(
        segment=selected,
        information_need=mock_fixture.information_need,
        user_memory=mock_fixture.user_memory,
        current_item_evidence=initial_state.candidates[1].evidence,
        metadata={},
    )
    perceiver = MockPerceiver(mock_fixture.perception_results)
    result = perceiver.observe(request)
    assert result.evidence.evidence_id == "evidence_b_1"
    assert perceiver.call_count == 1

    exception_perceiver = MockPerceiver(
        mock_fixture.perception_results,
        exception_identities={("item_b", "segment_1")},
    )
    with pytest.raises(ComponentExecutionError):
        exception_perceiver.observe(request)

    candidate_ids = mock_fixture.input.candidate_ids
    observations = empty_observation_state(candidate_ids, mock_fixture.segment_catalog)
    updated_observations = MockObservationUpdater().update(observations, result, 1)
    target = updated_observations.items[1].segment_observations[0]
    assert target.status is ObservationStatus.SUCCEEDED
    assert target.last_attempt_step == 1
    evidence = empty_evidence_state(candidate_ids)
    updated_evidence = MockEvidenceUpdater().update(evidence, result.evidence)
    assert updated_evidence.items[1].aggregated_attributes == {
        "mock_evidence_ids": ["evidence_b_1"]
    }
    with pytest.raises(ContractError, match="duplicate"):
        MockEvidenceUpdater().update(updated_evidence, result.evidence)
    with pytest.raises(ContractError, match="again"):
        MockObservationUpdater().update(updated_observations, result, 2)


def test_failed_observation_and_score_prior(mock_fixture: MockFixture) -> None:
    failed = PerceptionResult(
        item_id="item_b",
        segment_id="segment_1",
        status=ObservationStatus.FAILED,
        evidence=None,
        failure_code="mock_timeout",
        failure_reason="The deterministic mock timed out.",
        metadata={},
    )
    observations = empty_observation_state(
        mock_fixture.input.candidate_ids, mock_fixture.segment_catalog
    )
    updated = MockObservationUpdater().update(observations, failed, 1)
    assert updated.items[1].segment_observations[0].failure_reason

    evidence = empty_evidence_state(mock_fixture.input.candidate_ids)
    previous = tuple(
        (entry.item_id, entry.score) for entry in mock_fixture.initial_ranking.candidates
    )
    request = ScoreUpdateRequest(
        user_memory=mock_fixture.user_memory,
        initial_ranking=mock_fixture.initial_ranking,
        previous_scores=tuple(
            CandidateScore(item_id=item_id, score=score) for item_id, score in previous
        ),
        item_feature_refs=mock_fixture.item_feature_refs,
        evidence_state=evidence,
        metadata={},
    )
    scores = MockScoreUpdater(mock_fixture.score_deltas).update(request)
    assert tuple(entry.score for entry in scores) == tuple(score for _, score in previous)


def test_stop_policy_priority_and_safety(initial_state) -> None:
    policy = ThresholdStopPolicy(
        ranking_margin_threshold=0.01,
        min_segment_value=0.15,
    )
    assert policy.decide_pre_value(initial_state).reason is StopReason.RANKING_SUFFICIENTLY_CERTAIN
    low = SegmentValue(item_id="a", segment_id="s", value=0.1, metadata={})
    assert (
        policy.decide_post_value(initial_state, low).reason is StopReason.MAX_SEGMENT_VALUE_TOO_LOW
    )
    assert safety_decision(decision_loop_entries=2, max_decision_loop_entries=2) is None
    assert (
        safety_decision(decision_loop_entries=3, max_decision_loop_entries=2).reason
        is StopReason.SAFETY_LIMIT_REACHED
    )
    with pytest.raises(ValueError):
        ThresholdStopPolicy(ranking_margin_threshold=-1.0, min_segment_value=None)
