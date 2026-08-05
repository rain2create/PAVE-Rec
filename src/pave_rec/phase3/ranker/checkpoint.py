"""Immutable publication and exact loading of SASRec checkpoint bundles."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pave_rec.domain import ComponentDescriptor, ResourceRef
from pave_rec.domain.base import JsonObject
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import (
    ArtifactIntegrityError,
    ArtifactPublicationError,
    DatasetValidationError,
    ResourceResolutionError,
)
from pave_rec.phase3.derived import DerivedDatasetManifest, TrainVocabulary
from pave_rec.preprocessing.codecs import decode_canonical_json, encode_json
from pave_rec.preprocessing.paths import FilesystemPathResolver, RootRegistry, require_sha256
from pave_rec.preprocessing.publisher import publication_staging_key

from .checkpoint_models import (
    CHECKPOINT_IDENTITY_SCHEMA,
    CHECKPOINT_SCHEMA,
    CheckpointPublicationResult,
    SasrecCheckpointManifest,
    checkpoint_payload,
)
from .config import SasrecModelConfig, SasrecTrainingRecipeConfig


def _checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True)
class SasrecCheckpointPublicationPlan:
    checkpoint_id: str
    output_root_id: str
    manifest: SasrecCheckpointManifest
    manifest_ref: ResourceRef
    files: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        names = tuple(name for name, _ in self.files)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("checkpoint files require unique canonical names")
        expected = {payload.filename for payload in self.manifest.payloads}
        expected.add("checkpoint_manifest.json")
        if set(names) != expected:
            raise ValueError("checkpoint publication inventory mismatch")


def build_sasrec_checkpoint_plan(
    *,
    output_root_id: str,
    checkpoint_kind: Literal["best", "last"],
    model_config: SasrecModelConfig,
    training_recipe: SasrecTrainingRecipeConfig,
    source_data_version: str,
    source_release_ref: ResourceRef,
    derived_manifest_ref: ResourceRef,
    derived_manifest: DerivedDatasetManifest,
    vocabulary_ref: ResourceRef,
    vocabulary: TrainVocabulary,
    selected_best_manifest_ref: ResourceRef | None,
    epoch: int,
    global_step: int,
    best_epoch: int,
    validation_ndcg_at_10: float,
    best_validation_ndcg_at_10: float,
    model_state: bytes,
    optimizer_state: bytes | None,
    trainer_state: bytes | None,
    operational_provenance: JsonObject,
) -> SasrecCheckpointPublicationPlan:
    payload_bytes: dict[str, bytes] = {"model_state": model_state}
    if checkpoint_kind == "last":
        if optimizer_state is None or trainer_state is None:
            raise ValueError("last checkpoint requires optimizer and trainer state")
        payload_bytes.update(
            optimizer_state=optimizer_state,
            trainer_state=trainer_state,
        )
    elif optimizer_state is not None or trainer_state is not None:
        raise ValueError("best checkpoint contains model state only")
    payloads = tuple(
        checkpoint_payload(
            role=role,
            checksum=_checksum(payload_bytes[role]),
            size_bytes=len(payload_bytes[role]),
        )
        for role in ("model_state", "optimizer_state", "trainer_state")
        if role in payload_bytes
    )
    identity = {
        "identity_schema_version": CHECKPOINT_IDENTITY_SCHEMA,
        "checkpoint_kind": checkpoint_kind,
        "ranker_descriptor": {
            "role": "initial_ranker",
            "implementation": "SASRecInitialRanker",
            "version": "sasrec-pytorch-v1",
        },
        "model_config": model_config.model_dump(mode="json", exclude_none=False),
        "training_recipe": training_recipe.model_dump(mode="json", exclude_none=False),
        "source_data_version": source_data_version,
        "source_release_ref": source_release_ref.model_dump(mode="json", exclude_none=False),
        "derived_manifest_ref": derived_manifest_ref.model_dump(mode="json", exclude_none=False),
        "vocabulary_ref": vocabulary_ref.model_dump(mode="json", exclude_none=False),
        "selected_best_manifest_ref": (
            selected_best_manifest_ref.model_dump(mode="json", exclude_none=False)
            if selected_best_manifest_ref is not None
            else None
        ),
        "vocabulary_item_count": len(vocabulary.entries),
        "vocabulary_pad_index": vocabulary.pad_index,
        "epoch": epoch,
        "global_step": global_step,
        "best_epoch": best_epoch,
        "validation_ndcg_at_10": validation_ndcg_at_10,
        "best_validation_ndcg_at_10": best_validation_ndcg_at_10,
        "validation_protocol": "warm-full-catalog-seen-positive-mask-v1",
        "selection_rule": training_recipe.selection_rule,
        "stored_dtype": "float32",
        "weights_format": "pytorch-state-dict-v1",
        "payloads": [payload.model_dump(mode="json", exclude_none=False) for payload in payloads],
        "operational_provenance": operational_provenance,
    }
    checkpoint_id = (
        "p3ckpt-" + hashlib.sha256(canonical_json_bytes(identity, pretty=False)).hexdigest()
    )
    manifest = SasrecCheckpointManifest(
        schema_version=CHECKPOINT_SCHEMA,
        checkpoint_id=checkpoint_id,
        checkpoint_kind=checkpoint_kind,
        status="completed",
        ranker_descriptor=ComponentDescriptor(
            role="initial_ranker",
            implementation="SASRecInitialRanker",
            version="sasrec-pytorch-v1",
        ),
        model_recipe=model_config,
        training_recipe=training_recipe,
        source_data_version=source_data_version,
        source_release_ref=source_release_ref,
        derived_manifest_ref=derived_manifest_ref,
        vocabulary_ref=vocabulary_ref,
        selected_best_manifest_ref=selected_best_manifest_ref,
        vocabulary_item_count=len(vocabulary.entries),
        vocabulary_pad_index=vocabulary.pad_index,
        epoch=epoch,
        global_step=global_step,
        best_epoch=best_epoch,
        validation_ndcg_at_10=validation_ndcg_at_10,
        best_validation_ndcg_at_10=best_validation_ndcg_at_10,
        validation_protocol="warm-full-catalog-seen-positive-mask-v1",
        selection_rule=training_recipe.selection_rule,
        stored_dtype="float32",
        weights_format="pytorch-state-dict-v1",
        payloads=payloads,
        operational_provenance=operational_provenance,
    )
    manifest_payload = encode_json(manifest)
    manifest_ref = ResourceRef(
        store=output_root_id,
        key=f"bundles/{checkpoint_id}/checkpoint_manifest.json",
        version=checkpoint_id,
        checksum=_checksum(manifest_payload),
    )
    files = {payload.filename: payload_bytes[payload.role] for payload in payloads}
    files["checkpoint_manifest.json"] = manifest_payload
    if derived_manifest.derived_version != derived_manifest_ref.version:
        raise ValueError("derived manifest/ref mismatch")
    return SasrecCheckpointPublicationPlan(
        checkpoint_id=checkpoint_id,
        output_root_id=output_root_id,
        manifest=manifest,
        manifest_ref=manifest_ref,
        files=tuple(sorted(files.items())),
    )


class FilesystemSasrecCheckpointPublisher:
    def __init__(self, registry: RootRegistry) -> None:
        self._resolver = FilesystemPathResolver(registry)

    def _verify(self, plan: SasrecCheckpointPublicationPlan, directory: Path) -> None:
        expected = {name for name, _ in plan.files}
        try:
            actual_inventory = {
                path.relative_to(directory).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
            }
        except OSError as exc:
            raise ArtifactIntegrityError("cannot inventory SASRec checkpoint bundle") from exc
        if actual_inventory != expected:
            raise ArtifactIntegrityError("SASRec checkpoint inventory mismatch")
        for name, payload in plan.files:
            try:
                actual = directory.joinpath(name).read_bytes()
            except OSError as exc:
                raise ArtifactIntegrityError(
                    f"cannot read SASRec checkpoint payload: {name}"
                ) from exc
            if actual != payload:
                raise ArtifactIntegrityError(f"SASRec checkpoint payload mismatch: {name}")

    def publish(
        self,
        plan: SasrecCheckpointPublicationPlan,
        *,
        execution_id: str,
    ) -> CheckpointPublicationResult:
        target = self._resolver.resolve_new_path(
            plan.output_root_id,
            f"bundles/{plan.checkpoint_id}",
        )
        if target.exists():
            self._verify(plan, target)
            return CheckpointPublicationResult(outcome="reused", manifest_ref=plan.manifest_ref)
        stage = self._resolver.resolve_new_path(
            plan.output_root_id,
            publication_staging_key(plan.output_root_id, plan.checkpoint_id, execution_id),
        )
        try:
            stage.mkdir(parents=True, exist_ok=False)
            for name, payload in plan.files:
                with stage.joinpath(name).open("xb") as handle:
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
                return CheckpointPublicationResult(
                    outcome="reused",
                    manifest_ref=plan.manifest_ref,
                )
            raise ArtifactPublicationError("cannot publish SASRec checkpoint bundle") from exc
        self._verify(plan, target)
        return CheckpointPublicationResult(outcome="created", manifest_ref=plan.manifest_ref)


def load_sasrec_checkpoint_manifest(
    resolver: FilesystemPathResolver,
    manifest_ref: ResourceRef,
) -> SasrecCheckpointManifest:
    try:
        require_sha256(manifest_ref.checksum)
    except ValueError as exc:
        raise ArtifactIntegrityError("invalid SASRec checkpoint manifest checksum") from exc
    if manifest_ref.key != f"bundles/{manifest_ref.version}/checkpoint_manifest.json":
        raise ArtifactIntegrityError("SASRec checkpoint manifest key/version mismatch")
    try:
        payload = resolver.read_verified_bytes(manifest_ref)
    except ResourceResolutionError as exc:
        raise ArtifactIntegrityError("cannot verify SASRec checkpoint manifest") from exc
    try:
        manifest = decode_canonical_json(
            payload,
            SasrecCheckpointManifest,
            logical_name="SASRec checkpoint manifest",
        )
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError("invalid SASRec checkpoint manifest") from exc
    if manifest.checkpoint_id != manifest_ref.version:
        raise ArtifactIntegrityError("SASRec checkpoint ID/ref mismatch")
    return manifest


def load_sasrec_checkpoint_payloads(
    resolver: FilesystemPathResolver,
    manifest_ref: ResourceRef,
    manifest: SasrecCheckpointManifest,
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for descriptor in manifest.payloads:
        ref = ResourceRef(
            store=manifest_ref.store,
            key=f"bundles/{manifest.checkpoint_id}/{descriptor.filename}",
            version=manifest.checkpoint_id,
            checksum=descriptor.checksum,
        )
        try:
            payload = resolver.read_verified_bytes(ref, expected_size=descriptor.size_bytes)
        except ResourceResolutionError as exc:
            raise ArtifactIntegrityError(
                f"cannot verify SASRec checkpoint payload: {descriptor.role}"
            ) from exc
        payloads[descriptor.role] = payload
    return payloads
