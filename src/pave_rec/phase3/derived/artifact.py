"""Immutable publication and exact loading for Phase 3 derived datasets."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import (
    ArtifactIntegrityError,
    ArtifactPublicationError,
    DatasetValidationError,
)
from pave_rec.phase3.tsinghua import POSITIVE_RECIPE
from pave_rec.preprocessing.codecs import (
    decode_canonical_json,
    decode_jsonl,
    encode_json,
    encode_jsonl,
)
from pave_rec.preprocessing.paths import (
    FilesystemPathResolver,
    RootRegistry,
    require_sha256,
    validate_filesystem_key,
)
from pave_rec.preprocessing.publisher import publication_staging_key

from .builder import EVAL_NEGATIVE_SEED, MAX_HISTORY_LENGTH, DerivedDataset
from .models import (
    DERIVED_BUILDER_VERSION,
    DERIVED_VERSION_PATTERN,
    DEV_CANDIDATE_RECIPE,
    ELIGIBILITY_RECIPE,
    PRIMARY_CANDIDATE_RECIPE,
    SASREC_VIEW_RECIPE,
    SPLIT_RECIPE,
    VOCABULARY_RECIPE,
    DerivedDatasetManifest,
    DerivedUserSplit,
    DevelopmentCandidateSet,
    EvaluationSubset,
    TrainingSample,
    TrainVocabulary,
)


def _checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _ref(store: str, key: str, version: str, payload: bytes) -> ResourceRef:
    return ResourceRef(store=store, key=key, version=version, checksum=_checksum(payload))


@dataclass(frozen=True)
class DerivedDatasetPublicationPlan:
    derived_version: str
    output_root_id: str
    manifest: DerivedDatasetManifest
    manifest_ref: ResourceRef
    files: tuple[tuple[ResourceRef, bytes], ...]

    def __post_init__(self) -> None:
        keys = tuple(ref.key for ref, _ in self.files)
        if len(keys) != len(set(keys)) or keys != tuple(sorted(keys)):
            raise ValueError("derived publication files must use unique canonical key order")
        for ref, payload in self.files:
            if ref.store != self.output_root_id or ref.version != self.derived_version:
                raise ValueError("derived publication ref identity mismatch")
            if ref.checksum != _checksum(payload):
                raise ValueError("derived publication checksum mismatch")


@dataclass(frozen=True)
class DerivedPublicationResult:
    outcome: Literal["created", "reused"]
    manifest_ref: ResourceRef


def build_derived_publication_plan(
    dataset: DerivedDataset,
    *,
    output_root_id: str,
) -> DerivedDatasetPublicationPlan:
    payloads: dict[str, bytes] = {
        "test_subset.json": encode_json(dataset.test_subset),
        "training_samples.jsonl": encode_jsonl(dataset.training_samples),
        "user_splits.jsonl": encode_jsonl(dataset.user_splits),
        "validation_subset.json": encode_json(dataset.validation_subset),
        "vocabulary.json": encode_json(dataset.vocabulary),
    }
    include_development = dataset.development_candidate_recipe is not None
    if include_development != (dataset.eval_negative_seed is not None):
        raise ValueError("development candidate recipe and seed must agree")
    if include_development and (
        dataset.development_candidate_recipe != DEV_CANDIDATE_RECIPE
        or dataset.eval_negative_seed != EVAL_NEGATIVE_SEED
    ):
        raise ValueError("unsupported development candidate recipe or seed")
    if include_development:
        payloads["development_candidates.jsonl"] = encode_jsonl(dataset.development_candidates)
    identity = {
        "identity_schema_version": "p3-derived-dataset-identity-v1",
        "builder_version": DERIVED_BUILDER_VERSION,
        "source_data_version": dataset.source_data_version,
        "source_release_ref": dataset.source_release_ref.model_dump(
            mode="json", exclude_none=False
        ),
        "recipes": {
            "positive": POSITIVE_RECIPE,
            "split": SPLIT_RECIPE,
            "eligibility": ELIGIBILITY_RECIPE,
            "sasrec_view": SASREC_VIEW_RECIPE,
            "max_history_length": MAX_HISTORY_LENGTH,
            "vocabulary": VOCABULARY_RECIPE,
            "primary_candidates": PRIMARY_CANDIDATE_RECIPE,
            "development_candidates": dataset.development_candidate_recipe,
            "eval_negative_seed": dataset.eval_negative_seed,
        },
        "payload_checksums": {
            name: _checksum(payload) for name, payload in sorted(payloads.items())
        },
    }
    digest = hashlib.sha256(canonical_json_bytes(identity, pretty=False)).hexdigest()
    version = f"p3derived-{digest}"
    prefix = f"bundles/{version}"
    refs = {
        name: _ref(output_root_id, f"{prefix}/{name}", version, payload)
        for name, payload in payloads.items()
    }
    counts = {
        "development_candidate_sets": len(dataset.development_candidates),
        "eligible_users": len(dataset.user_splits),
        "test_cold_targets": len(dataset.test_subset.cold_target_sample_ids),
        "test_targets": len(dataset.test_subset.all_target_sample_ids),
        "test_warm_targets": len(dataset.test_subset.warm_target_sample_ids),
        "train_events": sum(len(split.train_events) for split in dataset.user_splits),
        "training_samples": len(dataset.training_samples),
        "validation_cold_targets": len(dataset.validation_subset.cold_target_sample_ids),
        "validation_targets": len(dataset.validation_subset.all_target_sample_ids),
        "validation_warm_targets": len(dataset.validation_subset.warm_target_sample_ids),
        "vocabulary_items": len(dataset.vocabulary.entries),
    }
    manifest = DerivedDatasetManifest(
        schema_version="p3-derived-dataset-manifest-v1",
        derived_version=version,
        source_data_version=dataset.source_data_version,
        source_release_ref=dataset.source_release_ref,
        positive_recipe=POSITIVE_RECIPE,
        split_recipe=SPLIT_RECIPE,
        eligibility_recipe=ELIGIBILITY_RECIPE,
        sasrec_view_recipe=SASREC_VIEW_RECIPE,
        max_history_length=MAX_HISTORY_LENGTH,
        vocabulary_recipe=VOCABULARY_RECIPE,
        primary_candidate_recipe=PRIMARY_CANDIDATE_RECIPE,
        development_candidate_recipe=dataset.development_candidate_recipe,
        eval_negative_seed=dataset.eval_negative_seed,
        payload_refs=tuple(sorted(refs.values(), key=lambda ref: (ref.store, ref.key))),
        counts=counts,
    )
    manifest_payload = encode_json(manifest)
    manifest_ref = _ref(
        output_root_id,
        f"{prefix}/derived_dataset_manifest.json",
        version,
        manifest_payload,
    )
    files = tuple(
        sorted(
            (
                *((refs[name], payload) for name, payload in payloads.items()),
                (manifest_ref, manifest_payload),
            ),
            key=lambda entry: entry[0].key,
        )
    )
    return DerivedDatasetPublicationPlan(
        derived_version=version,
        output_root_id=output_root_id,
        manifest=manifest,
        manifest_ref=manifest_ref,
        files=files,
    )


class FilesystemDerivedDatasetPublisher:
    def __init__(self, registry: RootRegistry) -> None:
        self._resolver = FilesystemPathResolver(registry)

    def _path(self, root_id: str, key: str) -> Path:
        return self._resolver.resolve_new_path(root_id, key)

    def _verify(self, plan: DerivedDatasetPublicationPlan, directory: Path) -> None:
        prefix = f"bundles/{plan.derived_version}/"
        expected: set[str] = set()
        for ref, payload in plan.files:
            relative = ref.key.removeprefix(prefix)
            expected.add(relative)
            try:
                actual = directory.joinpath(*relative.split("/")).read_bytes()
            except OSError as exc:
                raise ArtifactIntegrityError(
                    f"cannot verify derived dataset artifact: {relative}"
                ) from exc
            if actual != payload:
                raise ArtifactIntegrityError(f"derived dataset artifact mismatch: {relative}")
        try:
            actual_inventory = {
                path.relative_to(directory).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
            }
        except OSError as exc:
            raise ArtifactIntegrityError("cannot inventory derived dataset bundle") from exc
        if actual_inventory != expected:
            raise ArtifactIntegrityError("derived dataset bundle inventory mismatch")

    def publish(
        self,
        plan: DerivedDatasetPublicationPlan,
        *,
        execution_id: str,
    ) -> DerivedPublicationResult:
        target = self._path(plan.output_root_id, f"bundles/{plan.derived_version}")
        if target.exists():
            self._verify(plan, target)
            return DerivedPublicationResult("reused", plan.manifest_ref)
        stage = self._path(
            plan.output_root_id,
            publication_staging_key(
                plan.output_root_id,
                plan.derived_version,
                execution_id,
            ),
        )
        prefix = f"bundles/{plan.derived_version}/"
        try:
            stage.mkdir(parents=True, exist_ok=False)
            for ref, payload in plan.files:
                relative = ref.key.removeprefix(prefix)
                destination = stage.joinpath(*relative.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            self._verify(plan, stage)
            target.parent.mkdir(parents=True, exist_ok=True)
            stage.rename(target)
        except ArtifactIntegrityError:
            raise
        except OSError as exc:
            if target.exists():
                self._verify(plan, target)
                return DerivedPublicationResult("reused", plan.manifest_ref)
            raise ArtifactPublicationError("cannot publish derived dataset bundle") from exc
        self._verify(plan, target)
        return DerivedPublicationResult("created", plan.manifest_ref)


def _decode_jsonl_exact(payload: bytes, model_type, logical_name: str):
    try:
        records = decode_jsonl(payload, model_type, logical_name=logical_name)
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError(f"invalid derived dataset payload: {logical_name}") from exc
    if encode_jsonl(records) != payload:
        raise ArtifactIntegrityError(f"non-canonical derived dataset payload: {logical_name}")
    return records


def load_derived_dataset(
    resolver: FilesystemPathResolver,
    manifest_ref: ResourceRef,
) -> tuple[DerivedDatasetManifest, DerivedDataset]:
    try:
        require_sha256(manifest_ref.checksum)
        validate_filesystem_key(manifest_ref.key)
    except ValueError as exc:
        raise ArtifactIntegrityError(f"invalid derived manifest ref: {exc}") from exc
    if (
        DERIVED_VERSION_PATTERN.fullmatch(manifest_ref.version) is None
        or manifest_ref.key != f"bundles/{manifest_ref.version}/derived_dataset_manifest.json"
    ):
        raise ArtifactIntegrityError("derived manifest ref key/version mismatch")
    manifest_payload = resolver.read_verified_bytes(manifest_ref)
    try:
        manifest = decode_canonical_json(
            manifest_payload,
            DerivedDatasetManifest,
            logical_name="derived dataset manifest",
        )
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError("invalid derived dataset manifest") from exc
    if manifest.derived_version != manifest_ref.version:
        raise ArtifactIntegrityError("derived manifest identity mismatch")
    expected_names = {
        "test_subset.json",
        "training_samples.jsonl",
        "user_splits.jsonl",
        "validation_subset.json",
        "vocabulary.json",
    }
    if manifest.development_candidate_recipe is not None:
        expected_names.add("development_candidates.jsonl")
    refs: dict[str, ResourceRef] = {}
    prefix = f"bundles/{manifest.derived_version}/"
    for ref in manifest.payload_refs:
        if ref.store != manifest_ref.store or ref.version != manifest.derived_version:
            raise ArtifactIntegrityError("derived payload ref identity mismatch")
        name = ref.key.removeprefix(prefix)
        if "/" in name or name not in expected_names or name in refs:
            raise ArtifactIntegrityError("derived payload inventory mismatch")
        refs[name] = ref
    if set(refs) != expected_names:
        raise ArtifactIntegrityError("derived payload inventory mismatch")
    payloads = {name: resolver.read_verified_bytes(ref) for name, ref in refs.items()}
    try:
        vocabulary = decode_canonical_json(
            payloads["vocabulary.json"], TrainVocabulary, logical_name="train vocabulary"
        )
        validation = decode_canonical_json(
            payloads["validation_subset.json"],
            EvaluationSubset,
            logical_name="validation subset",
        )
        test = decode_canonical_json(
            payloads["test_subset.json"], EvaluationSubset, logical_name="test subset"
        )
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError("invalid derived singleton payload") from exc
    splits = _decode_jsonl_exact(payloads["user_splits.jsonl"], DerivedUserSplit, "user splits")
    samples = _decode_jsonl_exact(
        payloads["training_samples.jsonl"], TrainingSample, "training samples"
    )
    development = (
        _decode_jsonl_exact(
            payloads["development_candidates.jsonl"],
            DevelopmentCandidateSet,
            "development candidates",
        )
        if "development_candidates.jsonl" in payloads
        else ()
    )
    dataset = DerivedDataset(
        source_data_version=manifest.source_data_version,
        source_release_ref=manifest.source_release_ref,
        user_splits=splits,
        training_samples=samples,
        vocabulary=vocabulary,
        validation_subset=validation,
        test_subset=test,
        development_candidate_recipe=manifest.development_candidate_recipe,
        eval_negative_seed=manifest.eval_negative_seed,
        development_candidates=development,
    )
    expected_counts = {
        "development_candidate_sets": len(development),
        "eligible_users": len(splits),
        "test_cold_targets": len(test.cold_target_sample_ids),
        "test_targets": len(test.all_target_sample_ids),
        "test_warm_targets": len(test.warm_target_sample_ids),
        "train_events": sum(len(split.train_events) for split in splits),
        "training_samples": len(samples),
        "validation_cold_targets": len(validation.cold_target_sample_ids),
        "validation_targets": len(validation.all_target_sample_ids),
        "validation_warm_targets": len(validation.warm_target_sample_ids),
        "vocabulary_items": len(vocabulary.entries),
    }
    if manifest.counts != expected_counts:
        raise ArtifactIntegrityError("derived manifest count mismatch")
    return manifest, dataset
