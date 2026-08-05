# ruff: noqa: E402

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from pave_rec.agent.replay import replay_run
from pave_rec.cli import phase3 as phase3_cli
from pave_rec.domain import ComponentDescriptor, ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.fixture import MockFixture
from pave_rec.phase3 import build_agent_input_bundle
from pave_rec.phase3.derived import (
    TrainVocabulary,
    VocabularyEntry,
    build_derived_dataset,
    build_derived_publication_plan,
)
from pave_rec.phase3.derived import lifecycle as derived_lifecycle
from pave_rec.phase3.evaluation import lifecycle as evaluation_lifecycle
from pave_rec.phase3.input_bundle import (
    FilesystemAgentInputPublisher,
    build_development_agent_input,
)
from pave_rec.phase3.memory import lifecycle as memory_lifecycle
from pave_rec.phase3.ranker import (
    Phase3SasrecTrainingConfig,
    SasrecModel,
    load_sasrec_checkpoint_manifest,
)
from pave_rec.phase3.ranker import trainer as trainer_module
from pave_rec.phase3.runtime_config import Phase3RuntimeConfig
from pave_rec.phase3.semantics import (
    BgeM3SnapshotManifest,
    EmbeddingResult,
    FilesystemItemSemanticPublisher,
    FixtureEmbeddingProvider,
    build_item_semantic_artifact_plan,
    build_semantic_text,
)
from pave_rec.phase3.semantics import lifecycle as semantics_lifecycle
from pave_rec.phase3.semantics.models import ModelSnapshotFile
from pave_rec.phase3.tsinghua import TsinghuaSnapshotIdentity, adapt_tsinghua_snapshot
from pave_rec.preprocessing.components import CanonicalBehaviorProcessor
from pave_rec.preprocessing.config import load_preprocessing_config
from pave_rec.preprocessing.models import ItemFeatureRecord
from pave_rec.preprocessing.paths import FilesystemPathResolver, build_root_registry
from pave_rec.preprocessing.runner import preprocess_from_config
from pave_rec.ranking.initial.mock import MockInitialRanker
from pave_rec.stores.release import ReleaseLoader
from pave_rec.user_memory.mock import MockUserMemory


def _derived_fixture(repo_root: Path):
    root = repo_root / "tests/fixtures/phase3/tsinghua/v1"
    snapshot = TsinghuaSnapshotIdentity.model_validate_json((root / "snapshot.json").read_bytes())
    adapted = adapt_tsinghua_snapshot(snapshot, root)
    sequences = CanonicalBehaviorProcessor().process(adapted.behavior_events)
    version = f"p2-{'a' * 64}"
    dataset = build_derived_dataset(
        sequences=sequences,
        source_data_version=version,
        source_release_ref=ResourceRef(
            store="processed",
            key=f"releases/{version}.json",
            version=version,
            checksum=f"sha256:{'b' * 64}",
        ),
        include_development_candidates=False,
    )
    item_ids = tuple(
        sorted(
            (*tuple(entry.item_id for entry in dataset.vocabulary.entries), "zzzz-extra-item"),
            key=lambda value: value.encode("utf-8"),
        )
    )
    dataset = replace(
        dataset,
        vocabulary=TrainVocabulary(
            schema_version="p3-train-vocabulary-v1",
            recipe="train-positive-utf8-order-pad0-v1",
            pad_index=0,
            entries=tuple(
                VocabularyEntry(item_id=item_id, model_index=index)
                for index, item_id in enumerate(item_ids, start=1)
            ),
        ),
    )
    return dataset, build_derived_publication_plan(dataset, output_root_id="derived")


def _training_config(
    *,
    derived_ref: ResourceRef,
    roots: dict[str, tuple[Path, str]],
    output_root_id: str,
    resume_ref: ResourceRef | None = None,
) -> Phase3SasrecTrainingConfig:
    return Phase3SasrecTrainingConfig.model_validate(
        {
            "schema_version": "1",
            "kind": "phase3-sasrec-training",
            "storage": {
                "roots": {
                    root_id: {"path": str(path), "access": access}
                    for root_id, (path, access) in roots.items()
                }
            },
            "derived_manifest_ref": derived_ref.model_dump(mode="python"),
            "output_root_id": output_root_id,
            "resume_checkpoint_ref": resume_ref.model_dump(mode="python")
            if resume_ref is not None
            else None,
            "model": {
                "recipe": "sasrec-pytorch-v1",
                "max_history_length": 50,
                "hidden_size": 64,
                "block_count": 2,
                "attention_head_count": 2,
                "feed_forward_size": 256,
                "activation": "gelu",
                "normalization": "pre-ln-final-ln",
                "dropout": 0.2,
                "initializer_std": 0.02,
                "tied_item_embeddings": True,
                "pad_index": 0,
            },
            "training": {
                "loss": "sampled-binary-last-position-v1",
                "negative_sampler": "uniform-train-vocabulary-user-train-exclusion-v1",
                "negatives_per_positive": 1,
                "optimizer": "adam",
                "learning_rate": 0.001,
                "beta1": 0.9,
                "beta2": 0.98,
                "epsilon": 1e-8,
                "weight_decay": 0.0,
                "scheduler": "none",
                "batch_size": 128,
                "max_epochs": 200,
                "gradient_clip_global_norm": 5.0,
                "precision": "fp32",
                "amp": False,
                "validation_metric": "warm-full-catalog-ndcg-at-10",
                "selection_rule": "maximum-metric-earliest-epoch-v1",
                "patience": 10,
                "training_seed": 20260804,
            },
            "operational": {
                "device": "cpu",
                "loader_workers": 0,
                "candidate_chunk_size": 32,
                "evaluation_user_batch_size": 8,
            },
        }
    )


def test_tiny_training_and_resume_publish_exact_checkpoints(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, derived_plan = _derived_fixture(repo_root)
    derived_root = tmp_path / "derived"
    first_root = tmp_path / "checkpoints"
    second_root = tmp_path / "checkpoints-resumed"
    for root in (derived_root, first_root, second_root):
        root.mkdir()
    first_roots = {
        "derived": (derived_root, "read_only"),
        "checkpoints": (first_root, "write_new"),
    }
    first_registry = build_root_registry(first_roots, project_root=tmp_path)
    first_config = _training_config(
        derived_ref=derived_plan.manifest_ref,
        roots=first_roots,
        output_root_id="checkpoints",
    )
    config_path = tmp_path / "train.yaml"
    config_path.write_text("fixture\n", encoding="utf-8")

    loaded = SimpleNamespace(
        config=first_config,
        config_path=config_path,
        project_root=tmp_path,
        root_registry=first_registry,
    )
    monkeypatch.setattr(trainer_module, "load_phase3_sasrec_training_config", lambda _: loaded)
    monkeypatch.setattr(
        trainer_module,
        "load_derived_dataset",
        lambda resolver, ref: (derived_plan.manifest, dataset),
    )
    item_to_index, index_to_item = trainer_module._index_maps(dataset.vocabulary)
    validation_model = SasrecModel(
        vocabulary_size=len(dataset.vocabulary.entries),
        config=first_config.model,
    )
    validation_metric = trainer_module._validation_ndcg_at_10(
        model=validation_model,
        dataset=dataset,
        item_to_index=item_to_index,
        index_to_item=index_to_item,
        device=torch.device("cpu"),
        user_batch_size=8,
    )
    assert 0.0 <= validation_metric <= 1.0
    monkeypatch.setattr(trainer_module, "_validation_ndcg_at_10", lambda **kwargs: 0.5)
    first = trainer_module.train_initial_ranker_from_config(config_path)
    assert first.best_epoch == 1
    assert first.completed_epoch == 11
    assert first.global_step > 0
    first_resolver = FilesystemPathResolver(first_registry)
    best_manifest = load_sasrec_checkpoint_manifest(first_resolver, first.best_manifest_ref)
    last_manifest = load_sasrec_checkpoint_manifest(first_resolver, first.last_manifest_ref)
    assert best_manifest.checkpoint_kind == "best"
    assert last_manifest.checkpoint_kind == "last"

    resume_roots = {
        "derived": (derived_root, "read_only"),
        "checkpoints": (first_root, "read_only"),
        "checkpoints_resumed": (second_root, "write_new"),
    }
    resume_registry = build_root_registry(resume_roots, project_root=tmp_path)
    resume_config = _training_config(
        derived_ref=derived_plan.manifest_ref,
        roots=resume_roots,
        output_root_id="checkpoints_resumed",
        resume_ref=first.last_manifest_ref,
    )
    resumed_loaded = SimpleNamespace(
        config=resume_config,
        config_path=config_path,
        project_root=tmp_path,
        root_registry=resume_registry,
    )
    monkeypatch.setattr(
        trainer_module,
        "load_phase3_sasrec_training_config",
        lambda _: resumed_loaded,
    )
    resumed = trainer_module.train_initial_ranker_from_config(
        config_path,
        execution_id="tiny-resume",
    )
    assert resumed.best_outcome == "reused"
    assert resumed.best_manifest_ref == first.best_manifest_ref
    assert resumed.completed_epoch == 12


class _Phase3Memory:
    descriptor = ComponentDescriptor(
        role="user_memory",
        implementation="ArtifactUserMemory",
        version="dynamic-hybrid-memory-v1",
    )

    def __init__(self, fixture: MockFixture) -> None:
        self._delegate = MockUserMemory(fixture)

    def build_or_update(self, user_id: str, history: tuple[str, ...]):
        return self._delegate.build_or_update(user_id, history)


class _Phase3Ranker:
    descriptor = ComponentDescriptor(
        role="initial_ranker",
        implementation="SASRecInitialRanker",
        version="sasrec-pytorch-v1",
    )

    def __init__(self, fixture: MockFixture) -> None:
        self._delegate = MockInitialRanker(fixture)

    def score(self, user_id: str, sequence: tuple[str, ...], candidate_ids: tuple[str, ...]):
        return self._delegate.score(user_id, sequence, candidate_ids)


def _runtime_ref(label: str) -> ResourceRef:
    return ResourceRef(
        store="artifacts",
        key=f"refs/{label}.json",
        version=f"version-{label}",
        checksum=f"sha256:{label * 64}",
    )


def test_phase3_runtime_writes_three_files_replays_and_cli_summarizes(
    preprocessing_project: Path,
    mock_fixture: MockFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pave_rec.phase3 import runtime as runtime_module

    preprocessing_config = preprocessing_project / "configs/preprocessing/fixture.yaml"
    preprocessing = preprocess_from_config(preprocessing_config)
    loaded_preprocessing = load_preprocessing_config(preprocessing_config)
    release = ReleaseLoader(loaded_preprocessing.root_registry).load(preprocessing.release_ref)
    output_root = preprocessing_project / "runs/phase3"
    output_root.mkdir(parents=True)
    artifact_root = preprocessing_project / "artifacts/runtime-refs"
    artifact_root.mkdir()
    refs = {
        "p2_release_ref": _runtime_ref("1"),
        "derived_dataset_ref": _runtime_ref("2"),
        "item_semantics_ref": _runtime_ref("3"),
        "sasrec_checkpoint_ref": _runtime_ref("4"),
        "memory_snapshot_ref": _runtime_ref("5"),
        "agent_input_bundle_ref": _runtime_ref("6"),
    }
    run_id = "20260804T160000Z-abcdef12"
    config = Phase3RuntimeConfig.model_validate(
        {
            "schema_version": "1",
            "kind": "phase3-runtime",
            "seed": 7,
            "data_version": preprocessing.data_version,
            "device": "cpu",
            "storage": {
                "roots": {
                    "artifacts": {"path": str(artifact_root), "access": "read_only"},
                    "phase3_runs": {"path": str(output_root), "access": "write_new"},
                }
            },
            "run": {"output_root_id": "phase3_runs", "run_id": run_id},
            "agent": {"max_perception_actions": 0},
            "stop": {"ranking_margin_threshold": None, "min_segment_value": None},
            "components": {
                "user_memory": "artifact",
                "initial_ranker": "sasrec",
                "item_feature_store": "persistent",
                "segment_store": "persistent",
                "state_builder": "default",
                "information_need": "unavailable",
                "segment_value": "unavailable",
                "perceiver": "unavailable",
                "evidence_updater": "unavailable",
                "observation_updater": "unavailable",
                "score_updater": "unavailable",
                "stop_policy": "threshold",
                "trace_writer": "jsonl",
            },
            "artifacts": {key: value.model_dump(mode="python") for key, value in refs.items()},
        }
    )
    bundle = build_agent_input_bundle(
        user_id=mock_fixture.input.user_id,
        ordered_history_prefix=mock_fixture.input.history,
        candidate_ids=mock_fixture.input.candidate_ids,
        cutoff_identity="fixture-cutoff",
        derived_dataset_ref=refs["derived_dataset_ref"],
        candidate_set_ref=_runtime_ref("7"),
    )
    preflight = runtime_module._RuntimePreflight(
        config=config,
        project_root=preprocessing_project,
        loaded_release=release,
        derived_manifest=None,
        dataset=None,
        input_bundle=bundle,
        user_memory=_Phase3Memory(mock_fixture),
        initial_ranker=_Phase3Ranker(mock_fixture),
    )
    monkeypatch.setattr(runtime_module, "_preflight", lambda _: preflight)
    result = runtime_module.run_phase3_from_config("fixture.yaml")
    run_dir = output_root / run_id
    assert tuple(sorted(path.name for path in run_dir.iterdir())) == (
        "resolved_config.json",
        "result.json",
        "trace.jsonl",
    )
    assert replay_run(run_dir) == result
    assert phase3_cli.main(["replay", "--run-dir", str(run_dir)]) == 0
    output = capsys.readouterr().out
    assert f"run_id={run_id}" in output
    assert "candidate_count=3" in output

    for command in (
        "derive",
        "semantics",
        "train-ranker",
        "memory",
        "memory-audit",
        "evaluate",
        "run",
    ):
        assert callable(phase3_cli._lifecycle(command))
    with pytest.raises(AssertionError, match="unknown parsed"):
        phase3_cli._lifecycle("unknown")


def test_derived_and_evaluation_lifecycles_publish_fixture_artifacts(
    repo_root: Path,
    preprocessing_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, derived_plan = _derived_fixture(repo_root)
    preprocessing_config = preprocessing_project / "configs/preprocessing/fixture.yaml"
    preprocessing = preprocess_from_config(preprocessing_config)
    loaded_preprocessing = load_preprocessing_config(preprocessing_config)
    derived_root = preprocessing_project / "artifacts/phase3-derived"
    evaluation_root = preprocessing_project / "artifacts/phase3-evaluations"
    derived_root.mkdir()
    evaluation_root.mkdir()
    declarations = {
        root_id: (str(root.path), root.access)
        for root_id, root in loaded_preprocessing.root_registry.roots.items()
    }
    declarations["derived"] = (str(derived_root), "write_new")
    derived_registry = build_root_registry(declarations, project_root=preprocessing_project)
    derived_config = SimpleNamespace(
        source_release_ref=preprocessing.release_ref,
        include_development_candidates=True,
        eval_negative_seed=20260804,
        output_root_id="derived",
    )
    config_path = preprocessing_project / "configs/phase3-derived-fixture.yaml"
    config_path.write_text("fixture\n", encoding="utf-8")
    loaded_derived = SimpleNamespace(
        config=derived_config,
        config_path=config_path,
        project_root=preprocessing_project,
        root_registry=derived_registry,
    )
    monkeypatch.setattr(
        derived_lifecycle,
        "load_phase3_derived_sequences_config",
        lambda _: loaded_derived,
    )
    monkeypatch.setattr(derived_lifecycle, "build_derived_dataset", lambda **kwargs: dataset)
    derived_result = derived_lifecycle.derive_sequences_from_config(config_path)
    assert derived_result.outcome == "created"
    assert derived_result.training_sample_count == len(dataset.training_samples)

    evaluation_registry = build_root_registry(
        {
            "derived": (str(derived_root), "read_only"),
            "evaluations": (str(evaluation_root), "write_new"),
        },
        project_root=preprocessing_project,
    )
    evaluation_config = SimpleNamespace(
        derived_artifact_ref=derived_result.manifest_ref,
        method="mostpop-v1",
        checkpoint_ref=None,
        split="test",
        output_root_id="evaluations",
        device="cpu",
        candidate_chunk_size=16,
        user_batch_size=2,
    )
    loaded_evaluation = SimpleNamespace(
        config=evaluation_config,
        config_path=config_path,
        project_root=preprocessing_project,
        root_registry=evaluation_registry,
    )
    monkeypatch.setattr(
        evaluation_lifecycle,
        "load_phase3_evaluation_config",
        lambda _: loaded_evaluation,
    )
    monkeypatch.setattr(
        evaluation_lifecycle,
        "load_derived_dataset",
        lambda resolver, ref: (derived_plan.manifest, dataset),
    )
    evaluation = evaluation_lifecycle.evaluate_from_config(config_path)
    assert evaluation.outcome == "created"
    assert evaluation.all_target_count == len(dataset.user_splits)


def test_memory_lifecycle_builds_from_exact_fixture_semantics(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, derived_plan = _derived_fixture(repo_root)
    semantic_root = tmp_path / "semantics"
    memory_root = tmp_path / "memory"
    processed_root = tmp_path / "processed"
    derived_root = tmp_path / "derived"
    for root in (semantic_root, memory_root, processed_root, derived_root):
        root.mkdir()
    item_ids = tuple(
        sorted(
            {
                event.item_id
                for split in dataset.user_splits
                for target in (split.validation_target, split.test_target)
                for event in target.history
            }
        )
    )
    records = tuple(
        ItemFeatureRecord(
            schema_version="item-feature-v1",
            item_id=item_id,
            attributes={"tags": [item_id]},
            segment_count=0,
            payload_refs=(),
            metadata={},
        )
        for item_id in item_ids
    )
    specs = tuple(
        spec
        for record in records
        if (
            spec := build_semantic_text(
                record,
                source_data_version=dataset.source_data_version,
            )
        )
        is not None
    )
    unit = (1.0, *(0.0 for _ in range(1023)))
    provider = FixtureEmbeddingProvider({spec.semantic_text: unit for spec in specs})
    unique_texts = {spec.semantic_text_sha256: spec.semantic_text for spec in specs}
    encoded = provider.encode(tuple(unique_texts[key] for key in sorted(unique_texts)))
    semantic_plan = build_item_semantic_artifact_plan(
        output_root_id="semantics",
        source_data_version=dataset.source_data_version,
        source_release_ref=dataset.source_release_ref,
        source_item_count=len(records),
        specs=specs,
        embeddings_by_text_checksum=dict(zip(sorted(unique_texts), encoded, strict=True)),
        model_snapshot_checksum=provider.snapshot_checksum,
    )
    semantic_write_registry = build_root_registry(
        {"semantics": (str(semantic_root), "write_new")},
        project_root=tmp_path,
    )
    FilesystemItemSemanticPublisher(semantic_write_registry).publish(
        semantic_plan,
        execution_id="fixture-semantics",
    )
    memory_registry = build_root_registry(
        {
            "processed": (str(processed_root), "read_only"),
            "derived": (str(derived_root), "read_only"),
            "semantics": (str(semantic_root), "read_only"),
            "memory": (str(memory_root), "write_new"),
        },
        project_root=tmp_path,
    )
    config = SimpleNamespace(
        source_release_ref=dataset.source_release_ref,
        derived_artifact_ref=derived_plan.manifest_ref,
        semantic_artifact_ref=semantic_plan.manifest_ref,
        output_root_id="memory",
    )
    config_path = tmp_path / "memory.yaml"
    config_path.write_text("fixture\n", encoding="utf-8")
    loaded = SimpleNamespace(
        config=config,
        config_path=config_path,
        project_root=tmp_path,
        root_registry=memory_registry,
    )

    class FakeReleaseLoader:
        def __init__(self, registry) -> None:
            self.registry = registry

        def load(self, ref):
            return SimpleNamespace(data_version=dataset.source_data_version)

    monkeypatch.setattr(memory_lifecycle, "load_phase3_memory_config", lambda _: loaded)
    monkeypatch.setattr(memory_lifecycle, "ReleaseLoader", FakeReleaseLoader)
    monkeypatch.setattr(
        memory_lifecycle,
        "load_derived_dataset",
        lambda resolver, ref: (derived_plan.manifest, dataset),
    )
    result = memory_lifecycle.build_memory_from_config(config_path)
    assert result.outcome == "created"
    assert result.snapshot_count == len(dataset.user_splits) * 2
    assert result.semantic_observation_count > 0


def test_runtime_preflight_closes_fake_exact_graph_and_publishes_input(
    tmp_path: Path,
    mock_fixture: MockFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pave_rec.phase3 import runtime as runtime_module

    roots = {}
    for root_id in (
        "artifacts",
        "inputs",
        "phase3_runs",
    ):
        path = tmp_path / root_id
        path.mkdir()
        roots[root_id] = (str(path), "write_new" if root_id != "artifacts" else "read_only")
    registry = build_root_registry(roots, project_root=tmp_path)
    refs = {
        "p2_release_ref": _runtime_ref("1"),
        "derived_dataset_ref": _runtime_ref("2"),
        "item_semantics_ref": _runtime_ref("3"),
        "sasrec_checkpoint_ref": _runtime_ref("4"),
        "memory_snapshot_ref": _runtime_ref("5"),
        "agent_input_bundle_ref": ResourceRef(
            store="inputs",
            key="bundles/input/agent_input_bundle.json",
            version="version-input",
            checksum=f"sha256:{'6' * 64}",
        ),
    }
    source_version = f"p2-{'a' * 64}"
    config = Phase3RuntimeConfig.model_validate(
        {
            "schema_version": "1",
            "kind": "phase3-runtime",
            "seed": 7,
            "data_version": source_version,
            "device": "cpu",
            "storage": {
                "roots": {
                    "artifacts": {"path": roots["artifacts"][0], "access": "read_only"},
                    "inputs": {"path": roots["inputs"][0], "access": "read_only"},
                    "phase3_runs": {
                        "path": roots["phase3_runs"][0],
                        "access": "write_new",
                    },
                }
            },
            "run": {"output_root_id": "phase3_runs", "run_id": None},
            "agent": {"max_perception_actions": 0},
            "stop": {"ranking_margin_threshold": None, "min_segment_value": None},
            "components": {
                "user_memory": "artifact",
                "initial_ranker": "sasrec",
                "item_feature_store": "persistent",
                "segment_store": "persistent",
                "state_builder": "default",
                "information_need": "unavailable",
                "segment_value": "unavailable",
                "perceiver": "unavailable",
                "evidence_updater": "unavailable",
                "observation_updater": "unavailable",
                "score_updater": "unavailable",
                "stop_policy": "threshold",
                "trace_writer": "jsonl",
            },
            "artifacts": {key: value.model_dump(mode="python") for key, value in refs.items()},
        }
    )
    candidate_ref = ResourceRef(
        store="artifacts",
        key="derived/development_candidates.jsonl",
        version=refs["derived_dataset_ref"].version,
        checksum=f"sha256:{'7' * 64}",
    )
    bundle = build_agent_input_bundle(
        user_id=mock_fixture.input.user_id,
        ordered_history_prefix=mock_fixture.input.history,
        candidate_ids=mock_fixture.input.candidate_ids,
        cutoff_identity="fixture-cutoff",
        derived_dataset_ref=refs["derived_dataset_ref"],
        candidate_set_ref=candidate_ref,
    )
    target = SimpleNamespace(
        sample_id="target-sample",
        user_id=bundle.user_id,
        cutoff_identity=bundle.cutoff_identity,
        history=tuple(
            SimpleNamespace(item_id=item_id) for item_id in bundle.ordered_history_prefix
        ),
        target=SimpleNamespace(item_id=bundle.candidate_ids[0]),
    )
    candidate_set = SimpleNamespace(
        target_sample_id="target-sample",
        target_item_id=bundle.candidate_ids[0],
        negative_item_ids=bundle.candidate_ids[1:],
    )
    dataset = SimpleNamespace(
        development_candidates=(candidate_set,),
        user_splits=(
            SimpleNamespace(
                validation_target=target,
                test_target=SimpleNamespace(
                    sample_id="other-target",
                    user_id="other-user",
                    cutoff_identity="other-cutoff",
                    history=(SimpleNamespace(item_id="other-history"),),
                ),
            ),
        ),
        vocabulary=SimpleNamespace(entries=()),
    )
    manifest = SimpleNamespace(
        derived_version=refs["derived_dataset_ref"].version,
        source_release_ref=refs["p2_release_ref"],
        source_data_version=source_version,
        payload_refs=(candidate_ref,),
    )
    loaded_config = SimpleNamespace(
        config=config,
        project_root=tmp_path,
        root_registry=registry,
    )
    release = SimpleNamespace(
        data_version=source_version,
        item_feature_index=SimpleNamespace(
            entries=tuple(SimpleNamespace(item_id=item_id) for item_id in bundle.candidate_ids)
        ),
    )

    class FakeReleaseLoader:
        def __init__(self, root_registry) -> None:
            self.root_registry = root_registry

        def load(self, ref):
            return release

    fake_semantics = SimpleNamespace(
        manifest=SimpleNamespace(source_release_ref=refs["p2_release_ref"])
    )
    fake_memory = SimpleNamespace(
        manifest=SimpleNamespace(
            source_release_ref=refs["p2_release_ref"],
            derived_artifact_ref=refs["derived_dataset_ref"],
            semantic_artifact_ref=refs["item_semantics_ref"],
        )
    )
    fake_checkpoint = SimpleNamespace(
        source_release_ref=refs["p2_release_ref"],
        derived_manifest_ref=refs["derived_dataset_ref"],
    )
    fake_ranker = _Phase3Ranker(mock_fixture)
    monkeypatch.setattr(runtime_module, "load_phase3_runtime_config", lambda _: loaded_config)
    monkeypatch.setattr(runtime_module, "ReleaseLoader", FakeReleaseLoader)
    monkeypatch.setattr(runtime_module, "load_derived_dataset", lambda *args: (manifest, dataset))
    monkeypatch.setattr(runtime_module, "load_item_semantics", lambda *args: fake_semantics)
    monkeypatch.setattr(runtime_module, "load_memory_artifact", lambda *args: fake_memory)
    monkeypatch.setattr(runtime_module, "load_agent_input_bundle", lambda *args: bundle)
    monkeypatch.setattr(
        runtime_module, "load_sasrec_checkpoint_manifest", lambda *args: fake_checkpoint
    )
    monkeypatch.setattr(runtime_module, "ArtifactUserMemory", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        runtime_module,
        "load_sasrec_initial_ranker",
        lambda **kwargs: fake_ranker,
    )
    preflight = runtime_module._preflight("fixture.yaml")
    assert preflight.input_bundle == bundle
    assert preflight.initial_ranker is fake_ranker

    development_dataset = SimpleNamespace(
        development_candidates=(candidate_set,),
        user_splits=dataset.user_splits,
    )
    input_manifest = SimpleNamespace(payload_refs=(candidate_ref,))
    plan = build_development_agent_input(
        dataset=development_dataset,
        manifest=input_manifest,
        derived_manifest_ref=refs["derived_dataset_ref"],
        output_root_id="inputs",
        target_sample_id="target-sample",
    )
    input_registry = build_root_registry(
        {"inputs": (roots["inputs"][0], "write_new")},
        project_root=tmp_path,
    )
    publisher = FilesystemAgentInputPublisher(input_registry)
    assert publisher.publish(plan, execution_id="first").outcome == "created"
    assert publisher.publish(plan, execution_id="second").outcome == "reused"


def test_item_semantics_lifecycle_uses_persistent_p2_features_and_fake_provider(
    preprocessing_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preprocessing_config = preprocessing_project / "configs/preprocessing/fixture.yaml"
    preprocessing = preprocess_from_config(preprocessing_config)
    loaded_preprocessing = load_preprocessing_config(preprocessing_config)
    model_root = preprocessing_project / "artifacts/model"
    snapshot_root = model_root / "snapshot"
    manifest_root = preprocessing_project / "artifacts/model-manifest"
    semantics_root = preprocessing_project / "artifacts/phase3-semantics"
    snapshot_root.mkdir(parents=True)
    manifest_root.mkdir()
    semantics_root.mkdir()
    model_payload = b"fixture-model"
    (snapshot_root / "config.json").write_bytes(model_payload)
    model_manifest = BgeM3SnapshotManifest(
        schema_version="bge-m3-model-snapshot-v1",
        model_id="BAAI/bge-m3",
        revision="5617a9f61b028005a4858fdac845db406aefb181",
        files=(
            ModelSnapshotFile(
                relative_path="config.json",
                size_bytes=len(model_payload),
                checksum="sha256:" + hashlib.sha256(model_payload).hexdigest(),
            ),
        ),
    )
    manifest_payload = canonical_json_bytes(model_manifest, pretty=True)
    manifest_ref = ResourceRef(
        store="model_manifests",
        key="snapshot.json",
        version=model_manifest.revision,
        checksum="sha256:" + hashlib.sha256(manifest_payload).hexdigest(),
    )
    (manifest_root / "snapshot.json").write_bytes(manifest_payload)
    declarations = {
        root_id: (str(root.path), root.access)
        for root_id, root in loaded_preprocessing.root_registry.roots.items()
    }
    declarations.update(
        {
            "model": (str(model_root), "read_only"),
            "model_manifests": (str(manifest_root), "read_only"),
            "semantics": (str(semantics_root), "write_new"),
        }
    )
    registry = build_root_registry(declarations, project_root=preprocessing_project)
    config = SimpleNamespace(
        source_release_ref=preprocessing.release_ref,
        output_root_id="semantics",
        provider=SimpleNamespace(
            snapshot_manifest_ref=manifest_ref,
            model_root_id="model",
            model_directory_key="snapshot",
        ),
        operational=SimpleNamespace(device="cpu", batch_size=4),
    )
    config_path = preprocessing_project / "configs/semantics-fixture.yaml"
    config_path.write_text("fixture\n", encoding="utf-8")
    loaded = SimpleNamespace(
        config=config,
        config_path=config_path,
        project_root=preprocessing_project,
        root_registry=registry,
    )

    class FakeProvider:
        def __init__(self, **kwargs) -> None:
            self.snapshot_checksum = manifest_ref.checksum

        def encode(self, texts):
            vector = (1.0, *(0.0 for _ in range(1023)))
            return tuple(
                EmbeddingResult(vector=vector, token_count=len(text), was_truncated=False)
                for text in texts
            )

    monkeypatch.setattr(
        semantics_lifecycle,
        "load_phase3_item_semantics_config",
        lambda _: loaded,
    )
    monkeypatch.setattr(
        semantics_lifecycle,
        "build_semantic_text",
        lambda record, source_data_version: build_semantic_text(
            record.model_copy(update={"attributes": {"tags": [record.item_id]}}),
            source_data_version=source_data_version,
        ),
    )
    monkeypatch.setattr(semantics_lifecycle, "BgeM3EmbeddingProvider", FakeProvider)
    result = semantics_lifecycle.build_item_semantics_from_config(config_path)
    assert result.outcome == "created"
    assert result.source_item_count == 3
    assert result.semantic_item_count > 0
