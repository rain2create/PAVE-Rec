"""Torch-free immutable checkpoint manifest schemas."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from pave_rec.domain import ComponentDescriptor, ResourceRef
from pave_rec.domain.base import FrozenModel, JsonObject, require_finite
from pave_rec.preprocessing.identity import validate_data_version
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key

from .config import SasrecModelConfig, SasrecTrainingRecipeConfig

CHECKPOINT_ID_PATTERN = re.compile(r"^p3ckpt-[0-9a-f]{64}$")
CHECKPOINT_SCHEMA = "p3-sasrec-checkpoint-manifest-v1"
CHECKPOINT_IDENTITY_SCHEMA = "p3-sasrec-checkpoint-identity-v1"


class CheckpointPayload(FrozenModel):
    role: Literal["model_state", "optimizer_state", "trainer_state"]
    filename: Literal["model_state.pt", "optimizer_state.pt", "trainer_state.pt"]
    format: Literal[
        "pytorch-state-dict-v1", "pytorch-optimizer-state-v1", "pytorch-trainer-state-v1"
    ]
    checksum: str
    size_bytes: int

    @field_validator("checksum")
    @classmethod
    def _validate_checksum(cls, value: str) -> str:
        return require_sha256(value)

    @field_validator("size_bytes")
    @classmethod
    def _validate_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("checkpoint payload size must be positive")
        return value

    @model_validator(mode="after")
    def _validate_role_mapping(self) -> "CheckpointPayload":
        expected = {
            "model_state": ("model_state.pt", "pytorch-state-dict-v1"),
            "optimizer_state": ("optimizer_state.pt", "pytorch-optimizer-state-v1"),
            "trainer_state": ("trainer_state.pt", "pytorch-trainer-state-v1"),
        }
        if (self.filename, self.format) != expected[self.role]:
            raise ValueError("checkpoint payload role/filename/format mismatch")
        return self


class SasrecCheckpointManifest(FrozenModel):
    schema_version: Literal["p3-sasrec-checkpoint-manifest-v1"]
    checkpoint_id: str
    checkpoint_kind: Literal["best", "last"]
    status: Literal["completed"]
    ranker_descriptor: ComponentDescriptor
    model_recipe: SasrecModelConfig
    training_recipe: SasrecTrainingRecipeConfig
    source_data_version: str
    source_release_ref: ResourceRef
    derived_manifest_ref: ResourceRef
    vocabulary_ref: ResourceRef
    selected_best_manifest_ref: ResourceRef | None
    vocabulary_item_count: int
    vocabulary_pad_index: Literal[0]
    epoch: int
    global_step: int
    best_epoch: int
    validation_ndcg_at_10: float
    best_validation_ndcg_at_10: float
    validation_protocol: Literal["warm-full-catalog-seen-positive-mask-v1"]
    selection_rule: Literal["maximum-metric-earliest-epoch-v1"]
    stored_dtype: Literal["float32"]
    weights_format: Literal["pytorch-state-dict-v1"]
    payloads: tuple[CheckpointPayload, ...]
    operational_provenance: JsonObject

    @field_validator("checkpoint_id")
    @classmethod
    def _validate_checkpoint_id(cls, value: str) -> str:
        if CHECKPOINT_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("checkpoint_id must be p3ckpt-<64 lowercase hex>")
        return value

    @field_validator("source_data_version")
    @classmethod
    def _validate_data_version(cls, value: str) -> str:
        return validate_data_version(value)

    @field_validator("epoch", "global_step", "best_epoch", "vocabulary_item_count")
    @classmethod
    def _validate_positive_int(cls, value: int, info: ValidationInfo) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return value

    @field_validator("validation_ndcg_at_10", "best_validation_ndcg_at_10")
    @classmethod
    def _validate_metric(cls, value: float, info: ValidationInfo) -> float:
        require_finite(value, info.field_name)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{info.field_name} must be in [0, 1]")
        return value

    @model_validator(mode="after")
    def _validate_closed_manifest(self) -> "SasrecCheckpointManifest":
        descriptor = self.ranker_descriptor
        if (
            descriptor.role,
            descriptor.implementation,
            descriptor.version,
        ) != ("initial_ranker", "SASRecInitialRanker", "sasrec-pytorch-v1"):
            raise ValueError("invalid SASRec ranker descriptor")
        expected_roles = (
            ("model_state",)
            if self.checkpoint_kind == "best"
            else ("model_state", "optimizer_state", "trainer_state")
        )
        roles = tuple(payload.role for payload in self.payloads)
        if roles != expected_roles:
            raise ValueError("checkpoint payload inventory does not match checkpoint kind")
        if self.best_epoch > self.epoch:
            raise ValueError("best epoch cannot be later than checkpoint epoch")
        if self.checkpoint_kind == "best" and self.best_epoch != self.epoch:
            raise ValueError("best checkpoint epoch must equal best_epoch")
        if self.checkpoint_kind == "best" and (
            self.validation_ndcg_at_10 != self.best_validation_ndcg_at_10
        ):
            raise ValueError("best checkpoint metric mismatch")
        if self.checkpoint_kind == "best" and self.selected_best_manifest_ref is not None:
            raise ValueError("best checkpoint must not point to another selected best")
        if self.checkpoint_kind == "last" and self.selected_best_manifest_ref is None:
            raise ValueError("last checkpoint requires its exact selected-best ref")
        refs = {
            "source_release_ref": self.source_release_ref,
            "derived_manifest_ref": self.derived_manifest_ref,
            "vocabulary_ref": self.vocabulary_ref,
        }
        if self.selected_best_manifest_ref is not None:
            refs["selected_best_manifest_ref"] = self.selected_best_manifest_ref
        for name, ref in refs.items():
            try:
                validate_filesystem_key(ref.key)
                require_sha256(ref.checksum, f"{name}.checksum")
            except ValueError as exc:
                raise ValueError(f"invalid {name}: {exc}") from exc
        if (
            self.source_release_ref.version != self.source_data_version
            or self.source_release_ref.key != f"releases/{self.source_data_version}.json"
        ):
            raise ValueError("source release ref/data version mismatch")
        if self.derived_manifest_ref.version not in self.derived_manifest_ref.key:
            raise ValueError("derived manifest ref key/version mismatch")
        if self.vocabulary_ref.version != self.derived_manifest_ref.version:
            raise ValueError("vocabulary and derived versions must match")
        if self.vocabulary_ref.key != (
            f"bundles/{self.derived_manifest_ref.version}/vocabulary.json"
        ):
            raise ValueError("vocabulary ref key/version mismatch")
        if self.selected_best_manifest_ref is not None and (
            CHECKPOINT_ID_PATTERN.fullmatch(self.selected_best_manifest_ref.version) is None
            or self.selected_best_manifest_ref.key
            != (f"bundles/{self.selected_best_manifest_ref.version}/checkpoint_manifest.json")
        ):
            raise ValueError("selected best checkpoint ref key/version mismatch")
        return self


class CheckpointPublicationResult(FrozenModel):
    outcome: Literal["created", "reused"]
    manifest_ref: ResourceRef


def checkpoint_payload(
    *,
    role: Literal["model_state", "optimizer_state", "trainer_state"],
    checksum: str,
    size_bytes: int,
) -> CheckpointPayload:
    mapping = {
        "model_state": ("model_state.pt", "pytorch-state-dict-v1"),
        "optimizer_state": ("optimizer_state.pt", "pytorch-optimizer-state-v1"),
        "trainer_state": ("trainer_state.pt", "pytorch-trainer-state-v1"),
    }
    filename, payload_format = mapping[role]
    return CheckpointPayload(
        role=role,
        filename=filename,
        format=payload_format,
        checksum=checksum,
        size_bytes=size_bytes,
    )
