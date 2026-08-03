from __future__ import annotations

from pathlib import Path

from pave_rec.agent.controller import AgentComponents, AgentController
from pave_rec.agent.stop import ThresholdStopPolicy
from pave_rec.agent.trace_writer import JsonlTraceWriter
from pave_rec.config import COMPONENT_ROLE_ORDER
from pave_rec.domain import AgentRunRequest, AgentStepTrace, StopReason
from pave_rec.fixture import MockFixture
from pave_rec.information_need.mock import MockInformationNeedEstimator
from pave_rec.perception.mock import MockPerceiver
from pave_rec.preprocessing.config import load_preprocessing_config
from pave_rec.preprocessing.runner import preprocess_from_config
from pave_rec.ranking.initial.mock import MockInitialRanker
from pave_rec.ranking.update.mock import MockScoreUpdater
from pave_rec.recommendation_state.builder import DefaultRecommendationStateBuilder
from pave_rec.recommendation_state.updaters import MockEvidenceUpdater, MockObservationUpdater
from pave_rec.segment_value.mock import MockSegmentValueModel
from pave_rec.stores.filesystem import FilesystemItemFeatureStore, FilesystemSegmentStore
from pave_rec.stores.release import ReleaseLoader
from pave_rec.stores.resolver import FilesystemResourceResolver
from pave_rec.user_memory.mock import MockUserMemory


def test_persistent_stores_complete_canonical_two_action_agent_smoke(
    preprocessing_project: Path, mock_fixture: MockFixture
) -> None:
    config_path = preprocessing_project / "configs/preprocessing/fixture.yaml"
    preprocessing = preprocess_from_config(config_path)
    loaded_config = load_preprocessing_config(config_path)
    release = ReleaseLoader(loaded_config.root_registry).load(preprocessing.release_ref)
    resolver = FilesystemResourceResolver(release)
    item_store = FilesystemItemFeatureStore(release)
    segment_store = FilesystemSegmentStore(release)
    assert resolver.loaded_release is item_store.loaded_release is segment_store.loaded_release

    run_dir = preprocessing_project / "runs/persistent-agent-smoke"
    run_dir.mkdir()
    components = AgentComponents(
        user_memory=MockUserMemory(mock_fixture),
        initial_ranker=MockInitialRanker(mock_fixture),
        item_feature_store=item_store,
        segment_store=segment_store,
        state_builder=DefaultRecommendationStateBuilder(),
        information_need=MockInformationNeedEstimator(mock_fixture),
        segment_value=MockSegmentValueModel(mock_fixture.segment_values),
        perceiver=MockPerceiver(mock_fixture.perception_results),
        evidence_updater=MockEvidenceUpdater(),
        observation_updater=MockObservationUpdater(),
        score_updater=MockScoreUpdater(mock_fixture.score_deltas),
        stop_policy=ThresholdStopPolicy(
            ranking_margin_threshold=0.1,
            min_segment_value=0.15,
        ),
        trace_writer=JsonlTraceWriter(run_dir),
    )
    descriptors = tuple(getattr(components, role).descriptor for role in COMPONENT_ROLE_ORDER)
    controller = AgentController(
        expected_run_id="persistent-store-smoke",
        components=components,
        max_perception_actions=2,
        seed=7,
        data_version=preprocessing.data_version,
        component_descriptors=descriptors,
        git_commit=None,
        git_dirty=None,
        result_metadata={},
    )
    result = controller.run(
        AgentRunRequest(
            run_id="persistent-store-smoke",
            user_id=mock_fixture.input.user_id,
            user_history=mock_fixture.input.history,
            candidate_ids=mock_fixture.input.candidate_ids,
        )
    )

    assert result.succeeded
    assert result.data_version == preprocessing.data_version
    assert result.stop_decision.reason is StopReason.BUDGET_EXHAUSTED
    assert tuple(
        (candidate.item_id, candidate.current_score) for candidate in result.final_state.candidates
    ) == (("item_b", 0.87), ("item_a", 0.78), ("item_c", 0.61))
    traces = tuple(
        AgentStepTrace.model_validate_json(line)
        for line in (run_dir / "trace.jsonl").read_bytes().splitlines()
    )
    selected = tuple(
        (trace.selected_segment.item_id, trace.selected_segment.segment_id)
        for trace in traces
        if trace.selected_segment is not None
    )
    perceived = tuple(
        (trace.perception_result.item_id, trace.perception_result.segment_id)
        for trace in traces
        if trace.perception_result is not None
    )
    assert selected == perceived == (("item_b", "segment_1"), ("item_a", "segment_2"))
    assert descriptors[2] == item_store.descriptor
    assert descriptors[3] == segment_store.descriptor
