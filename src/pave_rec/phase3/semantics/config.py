"""Strict config for the pinned BGE-M3 item-semantic lifecycle."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.domain.base import FrozenModel
from pave_rec.phase3.config import LoadedPhase3Config, Phase3ConfigBase, load_phase3_config
from pave_rec.preprocessing.identity import validate_data_version
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key, validate_root_id

DEVICE_PATTERN = re.compile(r"^(cpu|cuda:[0-9]+)$")


class BgeM3ProviderConfig(FrozenModel):
    recipe: Literal["bge-m3-dense-v1"]
    model_id: Literal["BAAI/bge-m3"]
    revision: Literal["5617a9f61b028005a4858fdac845db406aefb181"]
    provider_package: Literal["FlagEmbedding"]
    provider_version: Literal["1.4.0"]
    pooling: Literal["official-dense-cls"]
    instruction: None
    max_tokens: Literal[1024]
    dimension: Literal[1024]
    dtype: Literal["float32"]
    normalization: Literal["l2-unit-v1"]
    model_root_id: str
    model_directory_key: str
    snapshot_manifest_ref: ResourceRef

    @field_validator("model_root_id")
    @classmethod
    def _validate_root(cls, value: str) -> str:
        return validate_root_id(value)

    @field_validator("model_directory_key")
    @classmethod
    def _validate_directory_key(cls, value: str) -> str:
        return validate_filesystem_key(value)

    @model_validator(mode="after")
    def _validate_snapshot_ref(self) -> "BgeM3ProviderConfig":
        validate_filesystem_key(self.snapshot_manifest_ref.key)
        require_sha256(self.snapshot_manifest_ref.checksum, "snapshot_manifest_ref.checksum")
        if self.snapshot_manifest_ref.version != self.revision:
            raise ValueError("snapshot manifest ref version must equal the pinned model revision")
        if self.snapshot_manifest_ref.key != f"bge-m3-{self.revision}-snapshot.json":
            raise ValueError("snapshot manifest ref key/revision mismatch")
        return self


class SemanticOperationalConfig(FrozenModel):
    device: str
    batch_size: int

    @field_validator("device")
    @classmethod
    def _validate_device(cls, value: str) -> str:
        if DEVICE_PATTERN.fullmatch(value) is None:
            raise ValueError("semantic device must be cpu or cuda:<non-negative index>")
        return value

    @field_validator("batch_size")
    @classmethod
    def _validate_batch(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("semantic batch_size must be positive")
        return value


class Phase3ItemSemanticsConfig(Phase3ConfigBase):
    kind: Literal["phase3-item-semantics"]
    source_release_ref: ResourceRef
    output_root_id: str
    semantic_text_recipe: Literal["tsv-item-semantic-text-v1"]
    provider: BgeM3ProviderConfig
    operational: SemanticOperationalConfig

    @field_validator("output_root_id")
    @classmethod
    def _validate_output_root(cls, value: str) -> str:
        return validate_root_id(value)

    @model_validator(mode="after")
    def _validate_roots_and_source(self) -> "Phase3ItemSemanticsConfig":
        validate_data_version(self.source_release_ref.version)
        validate_filesystem_key(self.source_release_ref.key)
        require_sha256(self.source_release_ref.checksum, "source_release_ref.checksum")
        if self.source_release_ref.key != f"releases/{self.source_release_ref.version}.json":
            raise ValueError("source release ref key/version mismatch")
        for label, root_id in (
            ("source_release_ref", self.source_release_ref.store),
            ("provider.model_root_id", self.provider.model_root_id),
            ("provider.snapshot_manifest_ref", self.provider.snapshot_manifest_ref.store),
        ):
            root = self.storage.roots.get(root_id)
            if root is None or root.access != "read_only":
                raise ValueError(f"{label} must use a declared read_only root")
        output = self.storage.roots.get(self.output_root_id)
        if output is None or output.access != "write_new":
            raise ValueError("output_root_id must reference a declared write_new root")
        if self.output_root_id in {
            self.source_release_ref.store,
            self.provider.model_root_id,
            self.provider.snapshot_manifest_ref.store,
        }:
            raise ValueError("semantic output root must be distinct from all inputs")
        return self


def load_phase3_item_semantics_config(
    config_path: str | Path,
) -> LoadedPhase3Config[Phase3ItemSemanticsConfig]:
    return load_phase3_config(config_path, Phase3ItemSemanticsConfig)
