"""Immutable publication and exact reload for full-catalog evaluation results."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.domain.base import FrozenModel, require_non_empty
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, ArtifactPublicationError, DatasetValidationError
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

from .evaluator import RankingEvaluation
from .models import RankingEvaluationAggregate, TargetRankingOutcome

EVALUATION_VERSION_PATTERN = re.compile(r"^p3eval-[0-9a-f]{64}$")


def _checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class EvaluationExecutionRecipe(FrozenModel):
    evaluator_version: Literal["full-catalog-evaluator-v2"]
    device: str
    candidate_chunk_size: int
    user_batch_size: int

    @field_validator("device")
    @classmethod
    def _validate_device(cls, value: str) -> str:
        return require_non_empty(value, "device")

    @field_validator("candidate_chunk_size", "user_batch_size")
    @classmethod
    def _validate_sizes(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("evaluation execution sizes must be positive")
        return value


class EvaluationArtifactManifest(FrozenModel):
    schema_version: Literal["p3-evaluation-artifact-manifest-v2"]
    evaluation_version: str
    source_release_ref: ResourceRef
    derived_artifact_ref: ResourceRef
    method: Literal["mostpop-v1", "sasrec-pytorch-v1"]
    checkpoint_ref: ResourceRef | None
    split: Literal["validation", "test"]
    candidate_recipe: Literal["full-train-vocabulary-seen-positive-mask-v1"]
    metric_recipe: Literal["single-target-macro-ranking-v1"]
    execution_recipe: EvaluationExecutionRecipe
    aggregate_ref: ResourceRef
    outcomes_ref: ResourceRef
    counts: dict[str, int]

    @field_validator("evaluation_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if EVALUATION_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("evaluation_version must be p3eval-<64 lowercase hex>")
        return value

    @model_validator(mode="after")
    def _validate_manifest(self) -> "EvaluationArtifactManifest":
        if (self.method == "sasrec-pytorch-v1") != (self.checkpoint_ref is not None):
            raise ValueError("SASRec method/checkpoint presence mismatch")
        for ref in (
            self.source_release_ref,
            self.derived_artifact_ref,
            self.checkpoint_ref,
            self.aggregate_ref,
            self.outcomes_ref,
        ):
            if ref is not None:
                require_sha256(ref.checksum)
                validate_filesystem_key(ref.key)
        if any(
            ref.version != self.evaluation_version
            for ref in (self.aggregate_ref, self.outcomes_ref)
        ):
            raise ValueError("evaluation payload version mismatch")
        if set(self.counts) != {"all_targets", "cold_targets", "warm_targets"}:
            raise ValueError("evaluation count inventory mismatch")
        if any(value < 0 for value in self.counts.values()):
            raise ValueError("evaluation counts must be non-negative")
        if self.counts["warm_targets"] + self.counts["cold_targets"] != self.counts["all_targets"]:
            raise ValueError("evaluation warm/cold counts do not partition all targets")
        return self


@dataclass(frozen=True)
class EvaluationArtifactPlan:
    evaluation_version: str
    output_root_id: str
    manifest: EvaluationArtifactManifest
    manifest_ref: ResourceRef
    files: tuple[tuple[ResourceRef, bytes], ...]


@dataclass(frozen=True)
class EvaluationPublicationResult:
    outcome: Literal["created", "reused"]
    manifest_ref: ResourceRef


@dataclass(frozen=True)
class LoadedEvaluationArtifact:
    manifest: EvaluationArtifactManifest
    aggregate: RankingEvaluationAggregate
    outcomes: tuple[TargetRankingOutcome, ...]


def build_evaluation_artifact_plan(
    *,
    output_root_id: str,
    source_release_ref: ResourceRef,
    derived_artifact_ref: ResourceRef,
    method: Literal["mostpop-v1", "sasrec-pytorch-v1"],
    checkpoint_ref: ResourceRef | None,
    evaluation: RankingEvaluation,
    device: str,
    candidate_chunk_size: int,
    user_batch_size: int,
) -> EvaluationArtifactPlan:
    aggregate_payload = encode_json(evaluation.aggregate)
    outcomes_payload = encode_jsonl(evaluation.outcomes)
    execution_recipe = EvaluationExecutionRecipe(
        evaluator_version="full-catalog-evaluator-v2",
        device=device,
        candidate_chunk_size=candidate_chunk_size,
        user_batch_size=user_batch_size,
    )
    identity = {
        "identity_schema_version": "p3-evaluation-artifact-identity-v2",
        "source_release_ref": source_release_ref.model_dump(mode="json", exclude_none=False),
        "derived_artifact_ref": derived_artifact_ref.model_dump(mode="json", exclude_none=False),
        "method": method,
        "checkpoint_ref": checkpoint_ref.model_dump(mode="json", exclude_none=False)
        if checkpoint_ref is not None
        else None,
        "split": evaluation.aggregate.split,
        "candidate_recipe": "full-train-vocabulary-seen-positive-mask-v1",
        "metric_recipe": "single-target-macro-ranking-v1",
        "execution_recipe": execution_recipe.model_dump(mode="json", exclude_none=False),
        "payload_checksums": {
            "aggregate_metrics.json": _checksum(aggregate_payload),
            "per_target_outcomes.jsonl": _checksum(outcomes_payload),
        },
    }
    evaluation_version = (
        "p3eval-" + hashlib.sha256(canonical_json_bytes(identity, pretty=False)).hexdigest()
    )
    prefix = f"bundles/{evaluation_version}"
    aggregate_ref = ResourceRef(
        store=output_root_id,
        key=f"{prefix}/aggregate_metrics.json",
        version=evaluation_version,
        checksum=_checksum(aggregate_payload),
    )
    outcomes_ref = ResourceRef(
        store=output_root_id,
        key=f"{prefix}/per_target_outcomes.jsonl",
        version=evaluation_version,
        checksum=_checksum(outcomes_payload),
    )
    aggregate = evaluation.aggregate
    manifest = EvaluationArtifactManifest(
        schema_version="p3-evaluation-artifact-manifest-v2",
        evaluation_version=evaluation_version,
        source_release_ref=source_release_ref,
        derived_artifact_ref=derived_artifact_ref,
        method=method,
        checkpoint_ref=checkpoint_ref,
        split=aggregate.split,
        candidate_recipe="full-train-vocabulary-seen-positive-mask-v1",
        metric_recipe="single-target-macro-ranking-v1",
        execution_recipe=execution_recipe,
        aggregate_ref=aggregate_ref,
        outcomes_ref=outcomes_ref,
        counts={
            "all_targets": aggregate.all_target_count,
            "cold_targets": aggregate.cold_target_count,
            "warm_targets": aggregate.warm_target_count,
        },
    )
    manifest_payload = encode_json(manifest)
    manifest_ref = ResourceRef(
        store=output_root_id,
        key=f"{prefix}/evaluation_manifest.json",
        version=evaluation_version,
        checksum=_checksum(manifest_payload),
    )
    return EvaluationArtifactPlan(
        evaluation_version=evaluation_version,
        output_root_id=output_root_id,
        manifest=manifest,
        manifest_ref=manifest_ref,
        files=tuple(
            sorted(
                (
                    (aggregate_ref, aggregate_payload),
                    (manifest_ref, manifest_payload),
                    (outcomes_ref, outcomes_payload),
                ),
                key=lambda entry: entry[0].key,
            )
        ),
    )


class FilesystemEvaluationArtifactPublisher:
    def __init__(self, registry: RootRegistry) -> None:
        self._resolver = FilesystemPathResolver(registry)

    @staticmethod
    def _verify(plan: EvaluationArtifactPlan, directory: Path) -> None:
        prefix = f"bundles/{plan.evaluation_version}/"
        expected = set()
        for ref, payload in plan.files:
            name = ref.key.removeprefix(prefix)
            expected.add(name)
            try:
                actual = directory.joinpath(name).read_bytes()
            except OSError as exc:
                raise ArtifactIntegrityError(f"cannot verify evaluation payload: {name}") from exc
            if actual != payload:
                raise ArtifactIntegrityError(f"evaluation payload mismatch: {name}")
        try:
            actual_files = {
                path.relative_to(directory).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
            }
        except OSError as exc:
            raise ArtifactIntegrityError("cannot inventory evaluation artifact") from exc
        if actual_files != expected:
            raise ArtifactIntegrityError("evaluation artifact inventory mismatch")

    def publish(
        self, plan: EvaluationArtifactPlan, *, execution_id: str
    ) -> EvaluationPublicationResult:
        target = self._resolver.resolve_new_path(
            plan.output_root_id, f"bundles/{plan.evaluation_version}"
        )
        if target.exists():
            self._verify(plan, target)
            return EvaluationPublicationResult("reused", plan.manifest_ref)
        stage = self._resolver.resolve_new_path(
            plan.output_root_id,
            publication_staging_key(plan.output_root_id, plan.evaluation_version, execution_id),
        )
        prefix = f"bundles/{plan.evaluation_version}/"
        try:
            stage.mkdir(parents=True, exist_ok=False)
            for ref, payload in plan.files:
                destination = stage.joinpath(ref.key.removeprefix(prefix))
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
                return EvaluationPublicationResult("reused", plan.manifest_ref)
            raise ArtifactPublicationError("cannot publish evaluation artifact") from exc
        self._verify(plan, target)
        return EvaluationPublicationResult("created", plan.manifest_ref)


def load_evaluation_artifact(
    resolver: FilesystemPathResolver, manifest_ref: ResourceRef
) -> LoadedEvaluationArtifact:
    try:
        manifest = decode_canonical_json(
            resolver.read_verified_bytes(manifest_ref),
            EvaluationArtifactManifest,
            logical_name="evaluation artifact manifest",
        )
        aggregate = decode_canonical_json(
            resolver.read_verified_bytes(manifest.aggregate_ref),
            RankingEvaluationAggregate,
            logical_name="evaluation aggregate",
        )
        outcomes_payload = resolver.read_verified_bytes(manifest.outcomes_ref)
        outcomes = decode_jsonl(
            outcomes_payload, TargetRankingOutcome, logical_name="evaluation outcomes"
        )
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError("invalid evaluation artifact") from exc
    if (
        manifest.evaluation_version != manifest_ref.version
        or manifest_ref.key != f"bundles/{manifest.evaluation_version}/evaluation_manifest.json"
    ):
        raise ArtifactIntegrityError("evaluation manifest identity mismatch")
    if encode_jsonl(outcomes) != outcomes_payload:
        raise ArtifactIntegrityError("non-canonical evaluation outcomes")
    if len(outcomes) != manifest.counts["all_targets"]:
        raise ArtifactIntegrityError("evaluation outcome count mismatch")
    if aggregate.split != manifest.split or aggregate.all_target_count != len(outcomes):
        raise ArtifactIntegrityError("evaluation aggregate/manifest mismatch")
    return LoadedEvaluationArtifact(manifest, aggregate, outcomes)
