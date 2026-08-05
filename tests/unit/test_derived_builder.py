from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pave_rec.domain import ResourceRef
from pave_rec.errors import ArtifactIntegrityError, DatasetValidationError
from pave_rec.phase3.derived import (
    DerivedDatasetManifest,
    DerivedDatasetPublicationPlan,
    DerivedPositiveEvent,
    DerivedTarget,
    DerivedUserSplit,
    DevelopmentCandidateSet,
    EvaluationSubset,
    FilesystemDerivedDatasetPublisher,
    TrainingSample,
    TrainVocabulary,
    VocabularyEntry,
    build_derived_dataset,
    build_derived_publication_plan,
    build_development_candidates,
    load_derived_dataset,
)
from pave_rec.phase3.tsinghua import TsinghuaSnapshotIdentity, adapt_tsinghua_snapshot
from pave_rec.preprocessing.components import CanonicalBehaviorProcessor
from pave_rec.preprocessing.paths import FilesystemPathResolver, build_root_registry


@pytest.fixture
def derived_fixture(repo_root: Path):
    root = repo_root / "tests/fixtures/phase3/tsinghua/v1"
    snapshot = TsinghuaSnapshotIdentity.model_validate_json((root / "snapshot.json").read_bytes())
    adapted = adapt_tsinghua_snapshot(snapshot, root)
    return CanonicalBehaviorProcessor().process(adapted.behavior_events)


def _source_identity() -> tuple[str, ResourceRef]:
    version = f"p2-{'a' * 64}"
    return version, ResourceRef(
        store="processed",
        key=f"releases/{version}.json",
        version=version,
        checksum=f"sha256:{'b' * 64}",
    )


def test_derived_builder_uses_leave_two_out_and_train_only_vocabulary(
    derived_fixture,
) -> None:
    version, release_ref = _source_identity()
    derived = build_derived_dataset(
        sequences=derived_fixture,
        source_data_version=version,
        source_release_ref=release_ref,
        include_development_candidates=False,
    )
    assert tuple(split.user_id for split in derived.user_splits) == (
        "tsv:user:fixture-a",
        "tsv:user:fixture-b",
    )
    assert len(derived.training_samples) == 5
    assert tuple(entry.item_id for entry in derived.vocabulary.entries) == (
        "tsv:item:1",
        "tsv:item:2",
        "tsv:item:3",
    )
    assert tuple(entry.model_index for entry in derived.vocabulary.entries) == (1, 2, 3)

    user_a, user_b = derived.user_splits
    assert tuple(event.item_id for event in user_a.train_events) == (
        "tsv:item:1",
        "tsv:item:2",
        "tsv:item:3",
        "tsv:item:1",
    )
    assert user_a.validation_target.target.item_id == "tsv:item:4"
    assert user_a.test_target.target.item_id == "tsv:item:5"
    assert user_a.validation_target.in_train_vocabulary is False
    assert user_a.test_target.in_train_vocabulary is False
    assert user_b.validation_target.target.item_id == "tsv:item:1"
    assert user_b.test_target.target.item_id == "tsv:item:2"
    assert user_b.validation_target.in_train_vocabulary is True
    assert user_b.test_target.in_train_vocabulary is True


def test_derived_builder_preserves_exact_positive_and_full_exposure_cutoffs(
    derived_fixture,
) -> None:
    version, release_ref = _source_identity()
    derived = build_derived_dataset(
        sequences=derived_fixture,
        source_data_version=version,
        source_release_ref=release_ref,
        include_development_candidates=False,
    )
    user_a = derived.user_splits[0]
    assert user_a.validation_target.history_end_interaction_index_exclusive == 4
    assert user_a.test_target.history_end_interaction_index_exclusive == 5
    assert user_a.validation_target.history == user_a.train_events
    assert user_a.test_target.history == (*user_a.train_events, user_a.validation_target.target)
    assert all(
        event.source_interaction_index
        < user_a.validation_target.history_end_interaction_index_exclusive
        for event in user_a.validation_target.history
    )
    assert user_a.validation_target.cutoff_identity.startswith("p3cutoff-")
    assert user_a.validation_target.sample_id.startswith("p3target-")
    assert tuple(sample.target.item_id for sample in derived.training_samples[:3]) == (
        "tsv:item:2",
        "tsv:item:3",
        "tsv:item:1",
    )


def test_derived_builder_materializes_warm_and_cold_partitions(derived_fixture) -> None:
    version, release_ref = _source_identity()
    derived = build_derived_dataset(
        sequences=derived_fixture,
        source_data_version=version,
        source_release_ref=release_ref,
        include_development_candidates=False,
    )
    for subset in (derived.validation_subset, derived.test_subset):
        assert len(subset.all_target_sample_ids) == 2
        assert len(subset.warm_target_sample_ids) == 1
        assert len(subset.cold_target_sample_ids) == 1
    assert derived.development_candidates == ()


def test_development_candidates_are_deterministic_train_only_and_exactly_100() -> None:
    history = (
        DerivedPositiveEvent(item_id="item-000", source_interaction_index=0, occurred_at_ms=0),
    )
    target_event = DerivedPositiveEvent(
        item_id="item-001",
        source_interaction_index=1,
        occurred_at_ms=1,
    )
    target = DerivedTarget(
        sample_id="target-1",
        user_id="user-1",
        split="validation",
        history=history,
        target=target_event,
        history_end_interaction_index_exclusive=1,
        cutoff_identity="cutoff-1",
        in_train_vocabulary=True,
    )
    vocabulary = TrainVocabulary(
        schema_version="p3-train-vocabulary-v1",
        recipe="train-positive-utf8-order-pad0-v1",
        pad_index=0,
        entries=tuple(
            VocabularyEntry(item_id=f"item-{index:03d}", model_index=index + 1)
            for index in range(105)
        ),
    )
    first = build_development_candidates(targets=(target,), vocabulary=vocabulary)
    second = build_development_candidates(targets=(target,), vocabulary=vocabulary)
    assert first == second
    assert len(first[0].negative_item_ids) == 100
    assert "item-000" not in first[0].negative_item_ids
    assert "item-001" not in first[0].negative_item_ids


def test_derived_builder_fails_when_fixed_dev_domain_is_too_small(derived_fixture) -> None:
    version, release_ref = _source_identity()
    with pytest.raises(DatasetValidationError, match="insufficient train-vocabulary negatives"):
        build_derived_dataset(
            sequences=derived_fixture,
            source_data_version=version,
            source_release_ref=release_ref,
            include_development_candidates=True,
        )


def test_derived_builder_rejects_source_identity_and_order_mismatch(derived_fixture) -> None:
    version, release_ref = _source_identity()
    with pytest.raises(DatasetValidationError, match="release ref/data version mismatch"):
        build_derived_dataset(
            sequences=derived_fixture,
            source_data_version=version,
            source_release_ref=release_ref.model_copy(update={"version": f"p2-{'c' * 64}"}),
            include_development_candidates=False,
        )
    with pytest.raises(DatasetValidationError, match="canonical user order"):
        build_derived_dataset(
            sequences=tuple(reversed(derived_fixture)),
            source_data_version=version,
            source_release_ref=release_ref,
            include_development_candidates=False,
        )


def test_derived_artifact_publishes_reuses_and_loads_exactly(
    derived_fixture,
    tmp_path: Path,
) -> None:
    version, release_ref = _source_identity()
    dataset = build_derived_dataset(
        sequences=derived_fixture,
        source_data_version=version,
        source_release_ref=release_ref,
        include_development_candidates=False,
    )
    root = tmp_path / "derived"
    root.mkdir()
    write_registry = build_root_registry(
        {"derived": (str(root), "write_new")}, project_root=tmp_path
    )
    plan = build_derived_publication_plan(dataset, output_root_id="derived")
    publisher = FilesystemDerivedDatasetPublisher(write_registry)
    assert publisher.publish(plan, execution_id="derive-first").outcome == "created"
    assert publisher.publish(plan, execution_id="derive-second").outcome == "reused"

    read_registry = build_root_registry(
        {"derived": (str(root), "read_only")}, project_root=tmp_path
    )
    manifest, loaded = load_derived_dataset(
        FilesystemPathResolver(read_registry), plan.manifest_ref
    )
    assert manifest == plan.manifest
    assert loaded == dataset
    assert manifest.counts["eligible_users"] == 2
    assert manifest.counts["training_samples"] == 5
    assert manifest.development_candidate_recipe is None


def test_derived_artifact_reuse_detects_corruption(derived_fixture, tmp_path: Path) -> None:
    version, release_ref = _source_identity()
    dataset = build_derived_dataset(
        sequences=derived_fixture,
        source_data_version=version,
        source_release_ref=release_ref,
        include_development_candidates=False,
    )
    root = tmp_path / "derived"
    root.mkdir()
    registry = build_root_registry({"derived": (str(root), "write_new")}, project_root=tmp_path)
    plan = build_derived_publication_plan(dataset, output_root_id="derived")
    publisher = FilesystemDerivedDatasetPublisher(registry)
    publisher.publish(plan, execution_id="derive-first")
    vocabulary_ref = next(
        ref for ref in plan.manifest.payload_refs if ref.key.endswith("/vocabulary.json")
    )
    path = registry.require("derived").path.joinpath(*vocabulary_ref.key.split("/"))
    path.write_bytes(b"corrupt")
    with pytest.raises(ArtifactIntegrityError, match="artifact mismatch"):
        publisher.publish(plan, execution_id="derive-second")


def _reject(model, value, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(value)


def test_derived_logical_records_reject_invalid_temporal_contracts(derived_fixture) -> None:
    version, release_ref = _source_identity()
    dataset = build_derived_dataset(
        sequences=derived_fixture,
        source_data_version=version,
        source_release_ref=release_ref,
        include_development_candidates=False,
    )
    event = dataset.user_splits[0].train_events[0]
    _reject(
        DerivedPositiveEvent,
        {"item_id": "", "source_interaction_index": 0, "occurred_at_ms": 0},
        "must be a non-empty string",
    )
    for field in ("source_interaction_index", "occurred_at_ms"):
        invalid = event.model_dump()
        invalid[field] = -1
        _reject(DerivedPositiveEvent, invalid, "must be non-negative")

    target = dataset.user_splits[0].validation_target
    base = target.model_dump(mode="python")
    for field in ("sample_id", "user_id", "cutoff_identity"):
        invalid = dict(base)
        invalid[field] = ""
        _reject(DerivedTarget, invalid, "must be a non-empty string")
    invalid = dict(base)
    invalid["history"] = ()
    _reject(DerivedTarget, invalid, "history must not be empty")
    invalid = dict(base)
    invalid["history"] = tuple(reversed(target.history))
    _reject(DerivedTarget, invalid, "preserve source interaction order")
    invalid = dict(base)
    invalid["history_end_interaction_index_exclusive"] = target.history[-1].source_interaction_index
    _reject(DerivedTarget, invalid, "crosses the exclusive")
    invalid = dict(base)
    invalid["target"] = target.target.model_copy(
        update={"source_interaction_index": target.target.source_interaction_index + 1}
    )
    _reject(DerivedTarget, invalid, "must equal the exclusive cutoff")

    sample = dataset.training_samples[0]
    sample_data = sample.model_dump(mode="python")
    for field in ("sample_id", "user_id"):
        invalid = dict(sample_data)
        invalid[field] = ""
        _reject(TrainingSample, invalid, "must be a non-empty string")
    invalid = dict(sample_data)
    invalid["history"] = ()
    _reject(TrainingSample, invalid, "history must not be empty")
    invalid = dict(sample_data)
    invalid["target"] = sample.target.model_copy(
        update={"source_interaction_index": sample.target.source_interaction_index + 1}
    )
    _reject(TrainingSample, invalid, "define the exclusive cutoff")
    invalid = dict(sample_data)
    invalid["history_end_interaction_index_exclusive"] = sample.history[0].source_interaction_index
    invalid["target"] = sample.target.model_copy(
        update={"source_interaction_index": sample.history[0].source_interaction_index}
    )
    _reject(TrainingSample, invalid, "crosses its target cutoff")


def test_derived_user_split_rejects_role_identity_and_history_mismatch(derived_fixture) -> None:
    version, release_ref = _source_identity()
    dataset = build_derived_dataset(
        sequences=derived_fixture,
        source_data_version=version,
        source_release_ref=release_ref,
        include_development_candidates=False,
    )
    split = dataset.user_splits[0]
    base = split.model_dump(mode="python")
    invalid = dict(base)
    invalid["user_id"] = ""
    _reject(DerivedUserSplit, invalid, "must be a non-empty string")
    invalid = dict(base)
    invalid["train_events"] = split.train_events[:2]
    _reject(DerivedUserSplit, invalid, "at least three train positives")
    invalid = dict(base)
    invalid["validation_target"] = split.validation_target.model_copy(update={"user_id": "other"})
    _reject(DerivedUserSplit, invalid, "user identity mismatch")
    invalid = dict(base)
    invalid["validation_target"] = split.validation_target.model_copy(update={"split": "test"})
    _reject(DerivedUserSplit, invalid, "roles are invalid")
    invalid = dict(base)
    invalid["validation_target"] = split.validation_target.model_copy(
        update={"history": split.train_events[:-1]}
    )
    _reject(DerivedUserSplit, invalid, "validation history")
    invalid = dict(base)
    invalid["test_target"] = split.test_target.model_copy(update={"history": split.train_events})
    _reject(DerivedUserSplit, invalid, "test history")


def test_vocabulary_subset_and_development_candidate_contracts() -> None:
    entries = tuple(
        VocabularyEntry(item_id=f"item-{index:03d}", model_index=index + 1) for index in range(101)
    )
    base_vocabulary = {
        "schema_version": "p3-train-vocabulary-v1",
        "recipe": "train-positive-utf8-order-pad0-v1",
        "pad_index": 0,
        "entries": entries,
    }
    _reject(TrainVocabulary, {**base_vocabulary, "entries": ()}, "must not be empty")
    _reject(
        TrainVocabulary,
        {**base_vocabulary, "entries": (entries[0], entries[0])},
        "must not contain duplicates",
    )
    _reject(
        TrainVocabulary,
        {**base_vocabulary, "entries": tuple(reversed(entries))},
        "canonical UTF-8 byte order",
    )
    _reject(
        TrainVocabulary,
        {
            **base_vocabulary,
            "entries": (entries[0], entries[1].model_copy(update={"model_index": 3})),
        },
        "contiguous from one",
    )
    _reject(
        VocabularyEntry,
        {"item_id": "", "model_index": 1},
        "must be a non-empty string",
    )
    _reject(VocabularyEntry, {"item_id": "item", "model_index": 0}, "must be positive")

    subset = {
        "schema_version": "p3-evaluation-subset-v1",
        "split": "test",
        "all_target_sample_ids": ("a", "b"),
        "warm_target_sample_ids": ("a",),
        "cold_target_sample_ids": ("b",),
    }
    _reject(
        EvaluationSubset,
        {**subset, "all_target_sample_ids": ("a", "a")},
        "must not contain duplicates",
    )
    _reject(EvaluationSubset, {**subset, "cold_target_sample_ids": ("a",)}, "must not overlap")
    _reject(EvaluationSubset, {**subset, "cold_target_sample_ids": ()}, "must partition")

    negatives = tuple(f"item-{index:03d}" for index in range(100))
    candidates = {
        "schema_version": "p3-development-candidates-v1",
        "recipe": "warm-target-plus-100-train-negatives-v1",
        "seed": 20260804,
        "target_sample_id": "sample",
        "target_item_id": "target",
        "history_item_ids": ("history",),
        "negative_item_ids": negatives,
    }
    for field in ("target_sample_id", "target_item_id"):
        invalid = dict(candidates)
        invalid[field] = ""
        _reject(DevelopmentCandidateSet, invalid, "must be a non-empty string")
    _reject(
        DevelopmentCandidateSet,
        {**candidates, "negative_item_ids": (*negatives[:-1], negatives[-2])},
        "must not contain duplicates",
    )
    _reject(
        DevelopmentCandidateSet,
        {**candidates, "negative_item_ids": negatives[:-1]},
        "exactly 100",
    )
    _reject(
        DevelopmentCandidateSet,
        {**candidates, "target_item_id": negatives[0]},
        "contain the labeled target",
    )
    _reject(
        DevelopmentCandidateSet,
        {**candidates, "history_item_ids": (negatives[0],)},
        "contain cutoff-prefix positives",
    )
    _reject(
        DevelopmentCandidateSet,
        {**candidates, "negative_item_ids": tuple(reversed(negatives))},
        "canonical UTF-8 byte order",
    )


def test_derived_manifest_and_publication_plan_reject_identity_drift(derived_fixture) -> None:
    version, release_ref = _source_identity()
    dataset = build_derived_dataset(
        sequences=derived_fixture,
        source_data_version=version,
        source_release_ref=release_ref,
        include_development_candidates=False,
    )
    plan = build_derived_publication_plan(dataset, output_root_id="derived")
    manifest = plan.manifest.model_dump(mode="python")
    _reject(DerivedDatasetManifest, {**manifest, "derived_version": "bad"}, "p3derived")
    _reject(
        DerivedDatasetManifest,
        {
            **manifest,
            "source_release_ref": release_ref.model_copy(update={"checksum": "bad"}),
        },
        "invalid source release identity",
    )
    _reject(
        DerivedDatasetManifest,
        {
            **manifest,
            "source_release_ref": release_ref.model_copy(update={"key": "releases/wrong.json"}),
        },
        "key/version mismatch",
    )
    _reject(
        DerivedDatasetManifest,
        {**manifest, "eval_negative_seed": 20260804},
        "both present or both absent",
    )
    refs = plan.manifest.payload_refs
    _reject(
        DerivedDatasetManifest,
        {**manifest, "payload_refs": (refs[0], refs[0], *refs[2:])},
        "must not contain duplicates",
    )
    _reject(
        DerivedDatasetManifest,
        {**manifest, "payload_refs": tuple(reversed(refs))},
        "canonical store/key order",
    )
    _reject(
        DerivedDatasetManifest,
        {
            **manifest,
            "payload_refs": (
                refs[0].model_copy(update={"version": "other"}),
                *refs[1:],
            ),
        },
        "payload key/version mismatch",
    )
    _reject(
        DerivedDatasetManifest,
        {
            **manifest,
            "payload_refs": (
                refs[0].model_copy(
                    update={
                        "key": f"bundles/{plan.derived_version}/nested/{refs[0].key.split('/')[-1]}"
                    }
                ),
                *refs[1:],
            ),
        },
        "direct bundle member",
    )
    _reject(DerivedDatasetManifest, {**manifest, "counts": {}}, "count inventory")
    counts = dict(manifest["counts"])
    counts["eligible_users"] = -1
    _reject(DerivedDatasetManifest, {**manifest, "counts": counts}, "non-negative")

    with pytest.raises(ValueError, match="unique canonical key order"):
        DerivedDatasetPublicationPlan(
            plan.derived_version,
            plan.output_root_id,
            plan.manifest,
            plan.manifest_ref,
            (plan.files[0], plan.files[0]),
        )
    ref, payload = plan.files[0]
    with pytest.raises(ValueError, match="ref identity mismatch"):
        DerivedDatasetPublicationPlan(
            plan.derived_version,
            plan.output_root_id,
            plan.manifest,
            plan.manifest_ref,
            ((ref.model_copy(update={"store": "other"}), payload),),
        )
    with pytest.raises(ValueError, match="checksum mismatch"):
        DerivedDatasetPublicationPlan(
            plan.derived_version,
            plan.output_root_id,
            plan.manifest,
            plan.manifest_ref,
            ((ref, b"corrupt"),),
        )
