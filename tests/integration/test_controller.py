from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from pave_rec.agent.controller import AgentComponents, AgentController
from pave_rec.agent.stop import ThresholdStopPolicy, continue_decision
from pave_rec.agent.trace_writer import JsonlTraceWriter
from pave_rec.config import COMPONENT_ROLE_ORDER
from pave_rec.domain import (
    AgentRunRequest,
    AgentStepTrace,
    ComponentDescriptor,
    ItemSegmentCatalog,
    ObservationStatus,
    PerceptionResult,
    SegmentValue,
    StopReason,
)
from pave_rec.errors import ComponentExecutionError, ContractError
from pave_rec.fixture import MockFixture
from pave_rec.information_need.mock import MockInformationNeedEstimator
from pave_rec.perception.mock import MockPerceiver
from pave_rec.ranking.initial.mock import MockInitialRanker
from pave_rec.ranking.update.mock import MockScoreUpdater
from pave_rec.recommendation_state.builder import DefaultRecommendationStateBuilder
from pave_rec.recommendation_state.updaters import MockEvidenceUpdater, MockObservationUpdater
from pave_rec.segment_value.mock import MockSegmentValueModel
from pave_rec.stores.in_memory import InMemoryItemFeatureStore, InMemorySegmentStore
from pave_rec.user_memory.mock import MockUserMemory


def _components(
    fixture: MockFixture,
    run_dir: Path,
    *,
    margin: float | None = 0.1,
    min_value: float | None = 0.15,
) -> AgentComponents:
    run_dir.mkdir()
    return AgentComponents(
        user_memory=MockUserMemory(fixture),
        initial_ranker=MockInitialRanker(fixture),
        item_feature_store=InMemoryItemFeatureStore(fixture.item_feature_refs),
        segment_store=InMemorySegmentStore(fixture.segment_catalog),
        state_builder=DefaultRecommendationStateBuilder(),
        information_need=MockInformationNeedEstimator(fixture),
        segment_value=MockSegmentValueModel(fixture.segment_values),
        perceiver=MockPerceiver(fixture.perception_results),
        evidence_updater=MockEvidenceUpdater(),
        observation_updater=MockObservationUpdater(),
        score_updater=MockScoreUpdater(fixture.score_deltas),
        stop_policy=ThresholdStopPolicy(
            ranking_margin_threshold=margin, min_segment_value=min_value
        ),
        trace_writer=JsonlTraceWriter(run_dir),
    )


def _controller(
    fixture: MockFixture,
    components: AgentComponents,
    *,
    budget: int = 2,
) -> AgentController:
    descriptors = tuple(getattr(components, role).descriptor for role in COMPONENT_ROLE_ORDER)
    return AgentController(
        expected_run_id="mock-v1-golden",
        components=components,
        max_perception_actions=budget,
        seed=7,
        data_version="mock-v1",
        component_descriptors=descriptors,
        git_commit=None,
        git_dirty=None,
        result_metadata={},
    )


def _request(fixture: MockFixture) -> AgentRunRequest:
    return AgentRunRequest(
        run_id="mock-v1-golden",
        user_id=fixture.input.user_id,
        user_history=fixture.input.history,
        candidate_ids=fixture.input.candidate_ids,
    )


def _run(tmp_path: Path, fixture: MockFixture, *, budget: int = 2, **kwargs):
    components = _components(fixture, tmp_path / "run", **kwargs)
    result = _controller(fixture, components, budget=budget).run(_request(fixture))
    return result, components


def test_canonical_controller_run(tmp_path: Path, mock_fixture: MockFixture) -> None:
    result, components = _run(tmp_path, mock_fixture)
    assert result.succeeded
    assert result.stop_decision.reason is StopReason.BUDGET_EXHAUSTED
    assert result.trace_record_count == 3
    assert result.attempted_perception_actions == 2
    assert tuple(
        (candidate.item_id, candidate.current_score) for candidate in result.final_state.candidates
    ) == (("item_b", 0.87), ("item_a", 0.78), ("item_c", 0.61))
    assert components.perceiver.call_count == 2
    lines = (tmp_path / "run/trace.jsonl").read_bytes().splitlines()
    traces = tuple(AgentStepTrace.model_validate_json(line) for line in lines)
    assert len(traces[0].segment_values) == 6
    assert len(traces[1].segment_values) == 5
    assert traces[2].state_before is None


@pytest.mark.parametrize(
    ("budget", "margin", "min_value", "reason"),
    [
        (0, 0.1, 0.15, StopReason.BUDGET_EXHAUSTED),
        (2, 0.01, 0.15, StopReason.RANKING_SUFFICIENTLY_CERTAIN),
    ],
)
def test_pre_value_stop_variants(
    tmp_path: Path,
    mock_fixture: MockFixture,
    budget: int,
    margin: float,
    min_value: float,
    reason: StopReason,
) -> None:
    result, components = _run(
        tmp_path, mock_fixture, budget=budget, margin=margin, min_value=min_value
    )
    assert result.stop_decision.reason is reason
    assert result.attempted_perception_actions == 0
    assert components.perceiver.call_count == 0
    assert result.trace_record_count == 1


def test_no_segments_and_low_values(tmp_path: Path, mock_fixture: MockFixture) -> None:
    no_segments = tuple(
        ItemSegmentCatalog(item_id=item_id, segments=(), segment_proxy_refs=())
        for item_id in mock_fixture.input.candidate_ids
    )
    components = _components(mock_fixture, tmp_path / "none")
    components = replace(components, segment_store=InMemorySegmentStore(no_segments))
    result = _controller(mock_fixture, components).run(_request(mock_fixture))
    assert result.stop_decision.reason is StopReason.NO_UNOBSERVED_SEGMENTS

    low_values = tuple(
        SegmentValue(
            item_id=value.item_id,
            segment_id=value.segment_id,
            value=0.01,
            metadata={},
        )
        for value in mock_fixture.segment_values
    )
    components = _components(mock_fixture, tmp_path / "low")
    components = replace(components, segment_value=MockSegmentValueModel(low_values))
    result = _controller(mock_fixture, components).run(_request(mock_fixture))
    assert result.stop_decision.reason is StopReason.MAX_SEGMENT_VALUE_TOO_LOW
    assert result.attempted_perception_actions == 0


def test_normal_failed_perception_continues(tmp_path: Path, mock_fixture: MockFixture) -> None:
    failed = PerceptionResult(
        item_id="item_b",
        segment_id="segment_1",
        status=ObservationStatus.FAILED,
        evidence=None,
        failure_code="mock_timeout",
        failure_reason="The deterministic mock timed out.",
        metadata={},
    )
    components = _components(mock_fixture, tmp_path / "failed")
    components = replace(
        components,
        perceiver=MockPerceiver(
            mock_fixture.perception_results,
            result_overrides={("item_b", "segment_1"): failed},
        ),
    )
    result = _controller(mock_fixture, components).run(_request(mock_fixture))
    assert result.succeeded and result.final_state.step == 2
    item_b = next(c for c in result.final_state.candidates if c.item_id == "item_b")
    assert item_b.segment_observations[0].status is ObservationStatus.FAILED
    assert item_b.evidence.evidence == ()


class _FailingUserMemory(MockUserMemory):
    def build_or_update(self, user_id: str, history: tuple[str, ...]):
        raise ComponentExecutionError("configured initialization failure")


class _FailingObservationUpdater(MockObservationUpdater):
    def update(self, state, result, attempt_step):
        raise ComponentExecutionError("configured observation failure")


class _FailingEvidenceUpdater(MockEvidenceUpdater):
    def update(self, state, evidence):
        raise ComponentExecutionError("configured evidence failure")


class _FailingScoreUpdater(MockScoreUpdater):
    def update(self, request):
        raise ComponentExecutionError("configured score failure")


@pytest.mark.parametrize(
    ("role", "expected_step", "has_evidence"),
    [
        ("perceiver", 0, False),
        ("observation_updater", 0, False),
        ("evidence_updater", 0, False),
        ("score_updater", 1, True),
    ],
)
def test_declared_failure_partial_progress(
    tmp_path: Path,
    mock_fixture: MockFixture,
    role: str,
    expected_step: int,
    has_evidence: bool,
) -> None:
    components = _components(mock_fixture, tmp_path / role)
    if role == "perceiver":
        replacement = MockPerceiver(
            mock_fixture.perception_results,
            exception_identities={("item_b", "segment_1")},
        )
    elif role == "observation_updater":
        replacement = _FailingObservationUpdater()
    elif role == "evidence_updater":
        replacement = _FailingEvidenceUpdater()
    else:
        replacement = _FailingScoreUpdater(mock_fixture.score_deltas)
    components = replace(components, **{role: replacement})
    result = _controller(mock_fixture, components).run(_request(mock_fixture))
    assert not result.succeeded
    assert result.stop_decision.reason is StopReason.COMPONENT_FAILURE
    assert result.stop_decision.details["component_role"] == role
    assert result.attempted_perception_actions == 1
    assert result.final_state.step == expected_step
    evidence_ids = {
        evidence.evidence_id
        for candidate in result.final_state.candidates
        for evidence in candidate.evidence.evidence
    }
    assert ("evidence_b_1" in evidence_ids) is has_evidence


def test_initialization_component_failure(tmp_path: Path, mock_fixture: MockFixture) -> None:
    components = _components(mock_fixture, tmp_path / "init")
    components = replace(components, user_memory=_FailingUserMemory(mock_fixture))
    result = _controller(mock_fixture, components).run(_request(mock_fixture))
    assert not result.succeeded and result.final_state is None
    assert result.attempted_perception_actions == 0
    trace = AgentStepTrace.model_validate_json((tmp_path / "init/trace.jsonl").read_bytes())
    assert trace.state_before is None and trace.state_after is None


class _FailingWriter:
    descriptor = ComponentDescriptor(
        role="trace_writer", implementation="JsonlTraceWriter", version="phase1-v1"
    )

    def __init__(self, *, fail_result: bool = False) -> None:
        self.records = []
        self.fail_result = fail_result

    def write_step(self, record) -> None:
        if not self.fail_result:
            raise ComponentExecutionError("configured trace step failure")
        self.records.append(record)

    def write_result(self, result) -> None:
        raise ComponentExecutionError("configured result failure")


def test_trace_writer_failures_propagate(tmp_path: Path, mock_fixture: MockFixture) -> None:
    components = _components(mock_fixture, tmp_path / "writer-step")
    perceiver = components.perceiver
    components = replace(components, trace_writer=_FailingWriter())
    with pytest.raises(ComponentExecutionError, match="trace step"):
        _controller(mock_fixture, components).run(_request(mock_fixture))
    assert perceiver.call_count == 1

    components = _components(mock_fixture, tmp_path / "writer-result")
    writer = _FailingWriter(fail_result=True)
    components = replace(components, trace_writer=writer)
    with pytest.raises(ComponentExecutionError, match="result"):
        _controller(mock_fixture, components, budget=0).run(_request(mock_fixture))
    assert len(writer.records) == 1


class _AlwaysContinuePolicy(ThresholdStopPolicy):
    def decide_pre_value(self, state):
        return continue_decision()


class _BadPrePolicy(ThresholdStopPolicy):
    def decide_pre_value(self, state):
        return self.decide_post_value(
            state,
            SegmentValue(item_id="item_a", segment_id="segment_1", value=-1.0, metadata={}),
        )


class _BadPostPolicy(ThresholdStopPolicy):
    def decide_post_value(self, state, best_segment_value):
        return ThresholdStopPolicy(
            ranking_margin_threshold=0.0, min_segment_value=None
        ).decide_pre_value(state)


@pytest.mark.parametrize("policy_kind", ["no_budget", "no_segments", "bad_pre", "bad_post"])
def test_controller_detects_policy_contract_violations(
    tmp_path: Path, mock_fixture: MockFixture, policy_kind: str
) -> None:
    components = _components(mock_fixture, tmp_path / policy_kind)
    budget = 2
    if policy_kind == "no_budget":
        policy = _AlwaysContinuePolicy(ranking_margin_threshold=None, min_segment_value=None)
        budget = 0
    elif policy_kind == "no_segments":
        policy = _AlwaysContinuePolicy(ranking_margin_threshold=None, min_segment_value=None)
        empty = tuple(
            ItemSegmentCatalog(item_id=item_id, segments=(), segment_proxy_refs=())
            for item_id in mock_fixture.input.candidate_ids
        )
        components = replace(components, segment_store=InMemorySegmentStore(empty))
    elif policy_kind == "bad_pre":
        policy = _BadPrePolicy(ranking_margin_threshold=None, min_segment_value=1.0)
    else:
        policy = _BadPostPolicy(ranking_margin_threshold=None, min_segment_value=None)
    components = replace(components, stop_policy=policy)
    result = _controller(mock_fixture, components, budget=budget).run(_request(mock_fixture))
    assert result.stop_decision.reason is StopReason.COMPONENT_FAILURE
    assert result.stop_decision.details["error_type"] == "ContractError"


def test_controller_rejects_request_identity_and_missing_lookups(
    tmp_path: Path, mock_fixture: MockFixture, initial_state
) -> None:
    components = _components(mock_fixture, tmp_path / "identity")
    controller = _controller(mock_fixture, components)
    request = _request(mock_fixture).model_copy(update={"run_id": "another"})
    with pytest.raises(ContractError, match="resolved"):
        controller.run(request)
    with pytest.raises(ContractError, match="selected item"):
        controller._candidate(initial_state, "missing")
    with pytest.raises(ContractError, match="missing from catalog"):
        controller._find_segment(
            mock_fixture.segment_catalog,
            SegmentValue(item_id="missing", segment_id="s", value=1.0, metadata={}),
        )
