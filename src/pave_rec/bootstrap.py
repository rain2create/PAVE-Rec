"""Explicit Phase 1 component construction with no reflection or discovery."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .agent.controller import AgentComponents, AgentController
from .agent.stop import ThresholdStopPolicy
from .agent.trace_writer import JsonlTraceWriter
from .config import COMPONENT_ROLE_ORDER, Phase1Config
from .domain import ComponentDescriptor
from .errors import ContractError
from .fixture import MockFixture
from .information_need.mock import MockInformationNeedEstimator
from .perception.mock import MockPerceiver
from .ranking.initial.mock import MockInitialRanker
from .ranking.update.mock import MockScoreUpdater
from .recommendation_state.builder import DefaultRecommendationStateBuilder
from .recommendation_state.updaters import MockEvidenceUpdater, MockObservationUpdater
from .segment_value.mock import MockSegmentValueModel
from .stores.in_memory import InMemoryItemFeatureStore, InMemorySegmentStore
from .user_memory.mock import MockUserMemory

EXPECTED_DESCRIPTOR_VALUES = {
    "user_memory": ("MockUserMemory", "mock-v1"),
    "initial_ranker": ("MockInitialRanker", "mock-v1"),
    "item_feature_store": ("InMemoryItemFeatureStore", "mock-v1"),
    "segment_store": ("InMemorySegmentStore", "mock-v1"),
    "state_builder": ("DefaultRecommendationStateBuilder", "phase1-v1"),
    "information_need": ("MockInformationNeedEstimator", "mock-v1"),
    "segment_value": ("MockSegmentValueModel", "mock-v1"),
    "perceiver": ("MockPerceiver", "mock-v1"),
    "evidence_updater": ("MockEvidenceUpdater", "mock-v1"),
    "observation_updater": ("MockObservationUpdater", "mock-v1"),
    "score_updater": ("MockScoreUpdater", "mock-v1"),
    "stop_policy": ("ThresholdStopPolicy", "phase1-v1"),
    "trace_writer": ("JsonlTraceWriter", "phase1-v1"),
}


def _collect_descriptors(components: AgentComponents) -> tuple[ComponentDescriptor, ...]:
    descriptors: list[ComponentDescriptor] = []
    for role in COMPONENT_ROLE_ORDER:
        descriptor = getattr(components, role).descriptor
        if descriptor.role != role:
            raise ContractError(f"component descriptor role mismatch for {role}")
        expected_implementation, expected_version = EXPECTED_DESCRIPTOR_VALUES[role]
        if (descriptor.implementation, descriptor.version) != (
            expected_implementation,
            expected_version,
        ):
            raise ContractError(f"unexpected component descriptor for {role}")
        descriptors.append(descriptor)
    return tuple(descriptors)


def build_controller(
    *,
    config: Phase1Config,
    fixture: MockFixture,
    run_dir: Path,
    git_commit: str | None = None,
    git_dirty: bool | None = None,
) -> AgentController:
    """Instantiate the fixed Phase 1 selector mapping and return a ready controller."""

    if config.run.run_id is None:
        raise ContractError("resolved config must contain the actual run ID")
    if fixture.fixture_version != config.data_version:
        raise ContractError("fixture and resolved-config data versions do not match")
    components = AgentComponents(
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
            ranking_margin_threshold=config.stop.ranking_margin_threshold,
            min_segment_value=config.stop.min_segment_value,
        ),
        trace_writer=JsonlTraceWriter(run_dir),
    )
    descriptors = _collect_descriptors(components)
    output_directory = str(PurePosixPath(config.run.output_root) / config.run.run_id)
    return AgentController(
        expected_run_id=config.run.run_id,
        components=components,
        max_perception_actions=config.agent.max_perception_actions,
        seed=config.seed,
        data_version=config.data_version,
        component_descriptors=descriptors,
        git_commit=git_commit,
        git_dirty=git_dirty,
        result_metadata={"output_directory": output_directory},
        schema_version=config.schema_version,
    )
