"""Strict records for immutable Dynamic Hybrid Memory artifacts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from pave_rec.domain import ResourceRef, UserMemoryView
from pave_rec.domain.base import FrozenModel, require_non_empty, require_unique
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key

MEMORY_ARTIFACT_PATTERN = re.compile(r"^p3memoryartifact-[0-9a-f]{64}$")
MEMORY_VERSION_PATTERN = re.compile(r"^p3memory-[0-9a-f]{64}$")
SNAPSHOT_ID_PATTERN = re.compile(r"^p3snapshot-[0-9a-f]{64}$")


class MemorySupportRecord(FrozenModel):
    item_id: str
    prototype_id: str
    source_interaction_index: int
    occurred_at_ms: int

    @field_validator("item_id", "prototype_id")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("source_interaction_index", "occurred_at_ms")
    @classmethod
    def _validate_non_negative(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value


class MemoryTrackRecord(FrozenModel):
    atom_id: str
    kind: Literal["long", "pending"]
    state: Literal["stable", "emerging", "fading", "inactive"]
    centroid_ref: ResourceRef
    centroid_row_index: int
    medoid_prototype_id: str
    medoid_text: str
    strength: float
    persistence: float
    supports: tuple[MemorySupportRecord, ...]

    @field_validator("atom_id", "medoid_prototype_id", "medoid_text")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("centroid_row_index")
    @classmethod
    def _validate_row(cls, value: int) -> int:
        if value < 0:
            raise ValueError("centroid_row_index must be non-negative")
        return value

    @field_validator("strength", "persistence")
    @classmethod
    def _validate_unit(cls, value: float, info: ValidationInfo) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{info.field_name} must be in [0, 1]")
        return value

    @model_validator(mode="after")
    def _validate_track(self) -> "MemoryTrackRecord":
        if not self.supports:
            raise ValueError("memory tracks require support records")
        indexes = tuple(entry.source_interaction_index for entry in self.supports)
        if indexes != tuple(sorted(indexes)):
            raise ValueError("memory track supports must be chronological")
        if self.kind == "pending" and self.state != "emerging":
            raise ValueError("pending tracks must be emerging")
        if self.kind == "long" and self.state == "emerging":
            raise ValueError("long tracks cannot be emerging")
        require_sha256(self.centroid_ref.checksum)
        validate_filesystem_key(self.centroid_ref.key)
        return self


class MemoryStateRecord(FrozenModel):
    schema_version: Literal["p3-memory-state-v1"]
    snapshot_id: str
    memory_version: str
    user_id: str
    cutoff_identity: str
    history_projection_checksum: str
    updated_at_ms: int | None
    tracks: tuple[MemoryTrackRecord, ...]
    observed_semantic_count: int
    promotion_count: int

    @field_validator("snapshot_id")
    @classmethod
    def _validate_snapshot(cls, value: str) -> str:
        if SNAPSHOT_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("snapshot_id must be p3snapshot-<64 lowercase hex>")
        return value

    @field_validator("memory_version")
    @classmethod
    def _validate_memory_version(cls, value: str) -> str:
        if MEMORY_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("memory_version must be p3memory-<64 lowercase hex>")
        return value

    @field_validator("user_id", "cutoff_identity")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("history_projection_checksum")
    @classmethod
    def _validate_history_checksum(cls, value: str) -> str:
        return require_sha256(value)

    @field_validator("updated_at_ms")
    @classmethod
    def _validate_timestamp(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("updated_at_ms must be non-negative")
        return value

    @field_validator("observed_semantic_count", "promotion_count")
    @classmethod
    def _validate_count(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_tracks(self) -> "MemoryStateRecord":
        require_unique(tuple(track.atom_id for track in self.tracks), "memory track IDs")
        return self


class MemoryViewRecord(FrozenModel):
    schema_version: Literal["p3-memory-view-record-v1"]
    snapshot_id: str
    user_id: str
    cutoff_identity: str
    history_projection_checksum: str
    view: UserMemoryView

    @field_validator("snapshot_id")
    @classmethod
    def _validate_snapshot(cls, value: str) -> str:
        if SNAPSHOT_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("snapshot_id must be p3snapshot-<64 lowercase hex>")
        return value

    @field_validator("user_id", "cutoff_identity")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("history_projection_checksum")
    @classmethod
    def _validate_checksum(cls, value: str) -> str:
        return require_sha256(value)


class MemorySnapshotIndexEntry(FrozenModel):
    schema_version: Literal["p3-memory-snapshot-index-entry-v1"]
    snapshot_id: str
    memory_version: str
    user_id: str
    cutoff_identity: str
    history_projection_checksum: str
    state_line_index: int
    state_record_checksum: str
    view_line_index: int
    view_record_checksum: str

    @field_validator("snapshot_id")
    @classmethod
    def _validate_snapshot(cls, value: str) -> str:
        if SNAPSHOT_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("snapshot_id must be p3snapshot-<64 lowercase hex>")
        return value

    @field_validator("memory_version")
    @classmethod
    def _validate_memory_version(cls, value: str) -> str:
        if MEMORY_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("memory_version must be p3memory-<64 lowercase hex>")
        return value

    @field_validator("user_id", "cutoff_identity")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("history_projection_checksum", "state_record_checksum", "view_record_checksum")
    @classmethod
    def _validate_checksums(cls, value: str) -> str:
        return require_sha256(value)

    @field_validator("state_line_index", "view_line_index")
    @classmethod
    def _validate_line(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value


class MemoryArtifactManifest(FrozenModel):
    schema_version: Literal["p3-memory-artifact-manifest-v1"]
    artifact_version: str
    source_release_ref: ResourceRef
    derived_artifact_ref: ResourceRef
    semantic_artifact_ref: ResourceRef
    memory_recipe: Literal["dynamic-hybrid-memory-v1"]
    recent_short_count: Literal[5]
    max_projected_long: Literal[20]
    match_threshold: Literal[0.7]
    ema_eta: Literal[0.2]
    promotion_distinct_times: Literal[2]
    persistence_saturation: Literal[5]
    recency_half_life_days: Literal[7.0]
    inactive_strength: Literal[0.1]
    states_ref: ResourceRef
    views_ref: ResourceRef
    snapshot_index_ref: ResourceRef
    long_embeddings_ref: ResourceRef | None
    similarity_matrices_ref: ResourceRef | None
    counts: dict[str, int]

    @field_validator("artifact_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if MEMORY_ARTIFACT_PATTERN.fullmatch(value) is None:
            raise ValueError("artifact_version must be p3memoryartifact-<64 lowercase hex>")
        return value

    @model_validator(mode="after")
    def _validate_manifest(self) -> "MemoryArtifactManifest":
        for ref in (
            self.source_release_ref,
            self.derived_artifact_ref,
            self.semantic_artifact_ref,
            self.states_ref,
            self.views_ref,
            self.snapshot_index_ref,
            self.long_embeddings_ref,
            self.similarity_matrices_ref,
        ):
            if ref is not None:
                require_sha256(ref.checksum)
                validate_filesystem_key(ref.key)
        output_refs = (
            self.states_ref,
            self.views_ref,
            self.snapshot_index_ref,
            self.long_embeddings_ref,
            self.similarity_matrices_ref,
        )
        if any(ref is not None and ref.version != self.artifact_version for ref in output_refs):
            raise ValueError("memory payload ref version mismatch")
        expected_counts = {
            "active_long_tracks",
            "inactive_long_tracks",
            "matrix_float_count",
            "pending_tracks",
            "promotions",
            "semantic_observations",
            "snapshots",
            "unprojected_long_tracks",
        }
        if set(self.counts) != expected_counts or any(value < 0 for value in self.counts.values()):
            raise ValueError("memory artifact count inventory mismatch")
        centroid_count = sum(
            self.counts[key]
            for key in (
                "active_long_tracks",
                "inactive_long_tracks",
                "pending_tracks",
                "unprojected_long_tracks",
            )
        )
        if (centroid_count > 0) != (self.long_embeddings_ref is not None):
            raise ValueError("memory embedding ref/count mismatch")
        if (self.counts["matrix_float_count"] > 0) != (self.similarity_matrices_ref is not None):
            raise ValueError("memory matrix ref/count mismatch")
        return self
