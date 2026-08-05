"""Real Phase 3 zero-budget bootstrap and unchanged Controller lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pave_rec.agent.controller import AgentComponents, AgentController
from pave_rec.agent.stop import ThresholdStopPolicy
from pave_rec.agent.trace_writer import JsonlTraceWriter
from pave_rec.config import COMPONENT_ROLE_ORDER, validate_run_id
from pave_rec.domain import AgentRunRequest, AgentRunResult, ComponentDescriptor
from pave_rec.domain.serialization import write_canonical_json
from pave_rec.errors import ArtifactIntegrityError, ContractError, RunInputError
from pave_rec.phase3.derived import DerivedDataset, DerivedDatasetManifest, load_derived_dataset
from pave_rec.phase3.memory import ArtifactUserMemory, load_memory_artifact
from pave_rec.phase3.ranker import (
    load_sasrec_checkpoint_manifest,
    load_sasrec_initial_ranker,
)
from pave_rec.phase3.semantics import load_item_semantics
from pave_rec.preprocessing.paths import FilesystemPathResolver
from pave_rec.recommendation_state.builder import DefaultRecommendationStateBuilder
from pave_rec.runner import collect_git_metadata, generate_run_id
from pave_rec.stores.filesystem import FilesystemItemFeatureStore, FilesystemSegmentStore
from pave_rec.stores.release import LoadedRelease, ReleaseLoader

from .input_bundle import AgentInputBundle, load_agent_input_bundle
from .runtime_config import (
    PHASE3_RUNTIME_DESCRIPTOR_VALUES,
    Phase3RuntimeConfig,
    load_phase3_runtime_config,
)
from .unavailable import (
    UnavailableEvidenceUpdater,
    UnavailableInformationNeedEstimator,
    UnavailableObservationUpdater,
    UnavailableScoreUpdater,
    UnavailableSegmentPerceiver,
    UnavailableSegmentValueModel,
)


@dataclass(frozen=True)
class _RuntimePreflight:
    config: Phase3RuntimeConfig
    project_root: Path
    loaded_release: LoadedRelease
    derived_manifest: DerivedDatasetManifest
    dataset: DerivedDataset
    input_bundle: AgentInputBundle
    user_memory: ArtifactUserMemory
    initial_ranker: object


def _validate_input_against_derived(
    bundle: AgentInputBundle,
    manifest: DerivedDatasetManifest,
    dataset: DerivedDataset,
) -> None:
    if bundle.derived_dataset_ref.version != manifest.derived_version:
        raise ArtifactIntegrityError("Agent input derived version mismatch")
    if bundle.candidate_set_ref not in manifest.payload_refs:
        raise ArtifactIntegrityError("Agent input candidate set ref is outside derived artifact")
    candidates = tuple(
        candidate
        for candidate in dataset.development_candidates
        if (
            candidate.target_item_id,
            *candidate.negative_item_ids,
        )
        == bundle.candidate_ids
    )
    targets = tuple(
        target
        for split in dataset.user_splits
        for target in (split.validation_target, split.test_target)
        if target.user_id == bundle.user_id
        and target.cutoff_identity == bundle.cutoff_identity
        and tuple(event.item_id for event in target.history) == bundle.ordered_history_prefix
    )
    if len(candidates) != 1 or len(targets) != 1:
        raise ArtifactIntegrityError("Agent input does not bind one exact development target")
    if candidates[0].target_sample_id != targets[0].sample_id:
        raise ArtifactIntegrityError("Agent input target/candidate sample mismatch")


def _preflight(config_path: str | Path) -> _RuntimePreflight:
    loaded = load_phase3_runtime_config(config_path)
    config = loaded.config
    paths = FilesystemPathResolver(loaded.root_registry)
    release = ReleaseLoader(loaded.root_registry).load(config.artifacts.p2_release_ref)
    derived_manifest, dataset = load_derived_dataset(paths, config.artifacts.derived_dataset_ref)
    semantics = load_item_semantics(paths, config.artifacts.item_semantics_ref)
    memory = load_memory_artifact(paths, config.artifacts.memory_snapshot_ref)
    bundle = load_agent_input_bundle(paths, config.artifacts.agent_input_bundle_ref)
    checkpoint = load_sasrec_checkpoint_manifest(paths, config.artifacts.sasrec_checkpoint_ref)
    if config.data_version != release.data_version:
        raise ArtifactIntegrityError("runtime data version/P2 release mismatch")
    if (
        derived_manifest.source_release_ref != config.artifacts.p2_release_ref
        or semantics.manifest.source_release_ref != config.artifacts.p2_release_ref
        or memory.manifest.source_release_ref != config.artifacts.p2_release_ref
        or checkpoint.source_release_ref != config.artifacts.p2_release_ref
    ):
        raise ArtifactIntegrityError("runtime source artifact closure mismatch")
    if (
        memory.manifest.derived_artifact_ref != config.artifacts.derived_dataset_ref
        or memory.manifest.semantic_artifact_ref != config.artifacts.item_semantics_ref
        or checkpoint.derived_manifest_ref != config.artifacts.derived_dataset_ref
        or bundle.derived_dataset_ref != config.artifacts.derived_dataset_ref
    ):
        raise ArtifactIntegrityError("runtime Phase 3 artifact closure mismatch")
    _validate_input_against_derived(bundle, derived_manifest, dataset)
    source_ids = {entry.item_id for entry in release.item_feature_index.entries}
    if any(item_id not in source_ids for item_id in bundle.candidate_ids):
        raise ArtifactIntegrityError("Agent candidate is outside P2 Store coverage")
    user_memory = ArtifactUserMemory(
        memory,
        bound_user_id=bundle.user_id,
        bound_cutoff_identity=bundle.cutoff_identity,
        bound_history_projection_checksum=bundle.history_prefix_sha256,
    )
    initial_ranker = load_sasrec_initial_ranker(
        resolver=paths,
        manifest_ref=config.artifacts.sasrec_checkpoint_ref,
        expected_derived_manifest_ref=config.artifacts.derived_dataset_ref,
        derived_manifest=derived_manifest,
        vocabulary=dataset.vocabulary,
        device=config.device,
        candidate_chunk_size=4096,
    )
    # Score once before run-directory allocation to close device/history/candidate coverage.
    initial_ranker.score(bundle.user_id, bundle.ordered_history_prefix, bundle.candidate_ids)
    return _RuntimePreflight(
        config=config,
        project_root=loaded.project_root,
        loaded_release=release,
        derived_manifest=derived_manifest,
        dataset=dataset,
        input_bundle=bundle,
        user_memory=user_memory,
        initial_ranker=initial_ranker,
    )


def _run_directory(root: Path, requested: str | None) -> tuple[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    if requested is not None:
        try:
            validate_run_id(requested)
        except ValueError as exc:
            raise RunInputError(str(exc)) from exc
        run_id = requested
    else:
        run_id = generate_run_id()
    directory = root / run_id
    try:
        directory.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise RunInputError(f"run directory already exists: {run_id}") from exc
    return run_id, directory


def _descriptors(components: AgentComponents) -> tuple[ComponentDescriptor, ...]:
    descriptors = tuple(getattr(components, role).descriptor for role in COMPONENT_ROLE_ORDER)
    if tuple(descriptor.role for descriptor in descriptors) != COMPONENT_ROLE_ORDER:
        raise ContractError("Phase 3 component descriptor role/order mismatch")
    for descriptor in descriptors:
        expected = PHASE3_RUNTIME_DESCRIPTOR_VALUES[descriptor.role]
        if (descriptor.implementation, descriptor.version) != expected:
            raise ContractError(f"unexpected Phase 3 component descriptor for {descriptor.role}")
    return descriptors


def run_phase3_from_config(config_path: str | Path) -> AgentRunResult:
    preflight = _preflight(config_path)
    config = preflight.config
    output = config.storage.roots[config.run.output_root_id]
    requested_root = Path(output.path)
    output_root = (
        requested_root if requested_root.is_absolute() else preflight.project_root / requested_root
    )
    run_id, run_dir = _run_directory(output_root, config.run.run_id)
    resolved = config.model_copy(update={"run": config.run.model_copy(update={"run_id": run_id})})
    write_canonical_json(run_dir / "resolved_config.json", resolved)
    metadata = collect_git_metadata(preflight.project_root)
    components = AgentComponents(
        user_memory=preflight.user_memory,
        initial_ranker=preflight.initial_ranker,
        item_feature_store=FilesystemItemFeatureStore(preflight.loaded_release),
        segment_store=FilesystemSegmentStore(preflight.loaded_release),
        state_builder=DefaultRecommendationStateBuilder(),
        information_need=UnavailableInformationNeedEstimator(),
        segment_value=UnavailableSegmentValueModel(),
        perceiver=UnavailableSegmentPerceiver(),
        evidence_updater=UnavailableEvidenceUpdater(),
        observation_updater=UnavailableObservationUpdater(),
        score_updater=UnavailableScoreUpdater(),
        stop_policy=ThresholdStopPolicy(
            ranking_margin_threshold=config.stop.ranking_margin_threshold,
            min_segment_value=config.stop.min_segment_value,
        ),
        trace_writer=JsonlTraceWriter(run_dir),
    )
    controller = AgentController(
        expected_run_id=run_id,
        components=components,
        max_perception_actions=config.agent.max_perception_actions,
        seed=config.seed,
        data_version=config.data_version,
        component_descriptors=_descriptors(components),
        git_commit=metadata.commit,
        git_dirty=metadata.dirty,
        result_metadata={
            "artifact_graph": config.artifacts.model_dump(mode="json", exclude_none=False),
            "output_directory": str(PurePosixPath(config.run.output_root_id) / run_id),
            "runtime_kind": "phase3-runtime",
        },
        schema_version=config.schema_version,
    )
    bundle = preflight.input_bundle
    request = AgentRunRequest(
        run_id=run_id,
        user_id=bundle.user_id,
        user_history=bundle.ordered_history_prefix,
        candidate_ids=bundle.candidate_ids,
    )
    return controller.run(request)
