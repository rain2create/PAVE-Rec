"""Strict configuration for the first pluggable SASRec training lifecycle."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.domain.base import FrozenModel
from pave_rec.phase3.config import LoadedPhase3Config, Phase3ConfigBase, load_phase3_config
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key, validate_root_id

DERIVED_VERSION_PATTERN = re.compile(r"^p3derived-[0-9a-f]{64}$")
CHECKPOINT_VERSION_PATTERN = re.compile(r"^p3ckpt-[0-9a-f]{64}$")
DEVICE_PATTERN = re.compile(r"^(cpu|cuda:[0-9]+)$")


class SasrecModelConfig(FrozenModel):
    recipe: Literal["sasrec-pytorch-v1"]
    max_history_length: Literal[50]
    hidden_size: Literal[64]
    block_count: Literal[2]
    attention_head_count: Literal[2]
    feed_forward_size: Literal[256]
    activation: Literal["gelu"]
    normalization: Literal["pre-ln-final-ln"]
    dropout: Literal[0.2]
    initializer_std: Literal[0.02]
    tied_item_embeddings: Literal[True]
    pad_index: Literal[0]


class SasrecTrainingRecipeConfig(FrozenModel):
    loss: Literal["sampled-binary-last-position-v1"]
    negative_sampler: Literal["uniform-train-vocabulary-user-train-exclusion-v1"]
    negatives_per_positive: Literal[1]
    optimizer: Literal["adam"]
    learning_rate: Literal[0.001]
    beta1: Literal[0.9]
    beta2: Literal[0.98]
    epsilon: Literal[1e-08]
    weight_decay: Literal[0.0]
    scheduler: Literal["none"]
    batch_size: Literal[128]
    max_epochs: Literal[200]
    gradient_clip_global_norm: Literal[5.0]
    precision: Literal["fp32"]
    amp: Literal[False]
    validation_metric: Literal["warm-full-catalog-ndcg-at-10"]
    selection_rule: Literal["maximum-metric-earliest-epoch-v1"]
    patience: Literal[10]
    training_seed: Literal[20260804]


class SasrecOperationalConfig(FrozenModel):
    device: str
    loader_workers: int
    candidate_chunk_size: int
    evaluation_user_batch_size: int

    @field_validator("device")
    @classmethod
    def _validate_device(cls, value: str) -> str:
        if DEVICE_PATTERN.fullmatch(value) is None:
            raise ValueError("device must be cpu or cuda:<non-negative index>")
        return value

    @field_validator(
        "loader_workers",
        "candidate_chunk_size",
        "evaluation_user_batch_size",
    )
    @classmethod
    def _validate_sizes(cls, value: int, info) -> int:
        if info.field_name == "loader_workers":
            if value < 0:
                raise ValueError("loader_workers must be non-negative")
        elif value <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return value


def _validate_exact_ref(ref: ResourceRef, *, kind: str) -> ResourceRef:
    validate_root_id(ref.store)
    validate_filesystem_key(ref.key)
    require_sha256(ref.checksum, f"{kind}.checksum")
    if kind == "derived_manifest_ref":
        if (
            DERIVED_VERSION_PATTERN.fullmatch(ref.version) is None
            or ref.key != f"bundles/{ref.version}/derived_dataset_manifest.json"
        ):
            raise ValueError("derived manifest ref key/version mismatch")
    else:
        if (
            CHECKPOINT_VERSION_PATTERN.fullmatch(ref.version) is None
            or ref.key != f"bundles/{ref.version}/checkpoint_manifest.json"
        ):
            raise ValueError("resume checkpoint ref key/version mismatch")
    return ref


class Phase3SasrecTrainingConfig(Phase3ConfigBase):
    kind: Literal["phase3-sasrec-training"]
    derived_manifest_ref: ResourceRef
    output_root_id: str
    resume_checkpoint_ref: ResourceRef | None = None
    model: SasrecModelConfig
    training: SasrecTrainingRecipeConfig
    operational: SasrecOperationalConfig

    @field_validator("output_root_id")
    @classmethod
    def _validate_output_root(cls, value: str) -> str:
        return validate_root_id(value)

    @model_validator(mode="after")
    def _validate_graph_and_roots(self) -> "Phase3SasrecTrainingConfig":
        _validate_exact_ref(self.derived_manifest_ref, kind="derived_manifest_ref")
        derived_root = self.storage.roots.get(self.derived_manifest_ref.store)
        if derived_root is None or derived_root.access != "read_only":
            raise ValueError("derived_manifest_ref must use a declared read_only root")
        output_root = self.storage.roots.get(self.output_root_id)
        if output_root is None or output_root.access != "write_new":
            raise ValueError("output_root_id must reference a declared write_new root")
        if self.derived_manifest_ref.store == self.output_root_id:
            raise ValueError("derived and checkpoint roots must be distinct")
        if self.resume_checkpoint_ref is not None:
            _validate_exact_ref(self.resume_checkpoint_ref, kind="resume_checkpoint_ref")
            resume_root = self.storage.roots.get(self.resume_checkpoint_ref.store)
            if resume_root is None or resume_root.access != "read_only":
                raise ValueError("resume_checkpoint_ref must use a declared read_only root")
            if self.resume_checkpoint_ref.store == self.output_root_id:
                raise ValueError("resume and checkpoint output roots must be distinct")
        return self


def load_phase3_sasrec_training_config(
    config_path: str | Path,
) -> LoadedPhase3Config[Phase3SasrecTrainingConfig]:
    return load_phase3_config(config_path, Phase3SasrecTrainingConfig)
