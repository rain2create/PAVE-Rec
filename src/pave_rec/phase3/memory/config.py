"""Strict lifecycle configuration for Dynamic Hybrid Memory snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.domain.base import FrozenModel
from pave_rec.phase3.config import LoadedPhase3Config, Phase3ConfigBase, load_phase3_config
from pave_rec.preprocessing.identity import validate_data_version
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key, validate_root_id


def _validate_exact_ref(ref: ResourceRef, field_name: str) -> ResourceRef:
    validate_root_id(ref.store)
    validate_filesystem_key(ref.key)
    require_sha256(ref.checksum, f"{field_name}.checksum")
    return ref


class DynamicMemoryRecipeConfig(FrozenModel):
    recipe: Literal["dynamic-hybrid-memory-v1"]
    recent_short_count: Literal[5]
    max_projected_long: Literal[20]
    match_threshold: Literal[0.7]
    ema_eta: Literal[0.2]
    promotion_distinct_times: Literal[2]
    persistence_saturation: Literal[5]
    recency_half_life_days: Literal[7.0]
    inactive_strength: Literal[0.1]


class Phase3MemoryConfig(Phase3ConfigBase):
    kind: Literal["phase3-memory"]
    source_release_ref: ResourceRef
    derived_artifact_ref: ResourceRef
    semantic_artifact_ref: ResourceRef
    output_root_id: str
    snapshot_scope: Literal["validation-and-test"]
    recipe: DynamicMemoryRecipeConfig

    @field_validator("output_root_id")
    @classmethod
    def _validate_output_root(cls, value: str) -> str:
        return validate_root_id(value)

    @model_validator(mode="after")
    def _validate_graph(self) -> "Phase3MemoryConfig":
        validate_data_version(self.source_release_ref.version)
        if self.source_release_ref.key != f"releases/{self.source_release_ref.version}.json":
            raise ValueError("source release ref key/version mismatch")
        for field_name in (
            "source_release_ref",
            "derived_artifact_ref",
            "semantic_artifact_ref",
        ):
            ref = _validate_exact_ref(getattr(self, field_name), field_name)
            root = self.storage.roots.get(ref.store)
            if root is None or root.access != "read_only":
                raise ValueError(f"{field_name} must reference a declared read_only root")
        output = self.storage.roots.get(self.output_root_id)
        if output is None or output.access != "write_new":
            raise ValueError("output_root_id must reference a declared write_new root")
        if self.output_root_id in {
            self.source_release_ref.store,
            self.derived_artifact_ref.store,
            self.semantic_artifact_ref.store,
        }:
            raise ValueError("memory output root must be distinct from every input root")
        return self


def load_phase3_memory_config(
    config_path: str | Path,
) -> LoadedPhase3Config[Phase3MemoryConfig]:
    return load_phase3_config(config_path, Phase3MemoryConfig)
