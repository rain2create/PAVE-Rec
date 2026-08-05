"""Portable identities and aggregate audit records for the Tsinghua adapter."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from pave_rec.domain.base import FrozenModel, require_non_empty
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key

TSINGHUA_SNAPSHOT_SCHEMA = "tsinghua-shortvideo-snapshot-v1"
TSINGHUA_ADAPTER_VERSION = "tsinghua-source-adapter-v1"
TSINGHUA_SOURCE_SCHEMA = "tsinghua-adapted-source-v1"
POSITIVE_RECIPE = "tsv-positive-v1"

EXPECTED_SNAPSHOT_FILES = (
    "README.md",
    "categories_cn_en.csv",
    "interaction_sampled.csv",
)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class SnapshotArtifactIdentity(FrozenModel):
    relative_path: str
    size_bytes: int
    checksum: str

    @field_validator("relative_path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return validate_filesystem_key(value)

    @field_validator("size_bytes")
    @classmethod
    def _validate_size(cls, value: int) -> int:
        if value < 0:
            raise ValueError("size_bytes must be non-negative")
        return value

    @field_validator("checksum")
    @classmethod
    def _validate_checksum(cls, value: str) -> str:
        return require_sha256(value)


class TsinghuaSnapshotIdentity(FrozenModel):
    schema_version: Literal["tsinghua-shortvideo-snapshot-v1"]
    snapshot_id: str
    upstream_commit: str
    artifacts: tuple[SnapshotArtifactIdentity, ...]

    @field_validator("artifacts", mode="before")
    @classmethod
    def _parse_yaml_artifacts(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("snapshot_id")
    @classmethod
    def _validate_snapshot_id(cls, value: str) -> str:
        return require_non_empty(value, "snapshot_id")

    @field_validator("upstream_commit")
    @classmethod
    def _validate_commit(cls, value: str) -> str:
        if COMMIT_PATTERN.fullmatch(value) is None:
            raise ValueError("upstream_commit must be 40 lowercase hex characters")
        return value

    @model_validator(mode="after")
    def _validate_inventory(self) -> "TsinghuaSnapshotIdentity":
        paths = tuple(entry.relative_path for entry in self.artifacts)
        if paths != EXPECTED_SNAPSHOT_FILES:
            raise ValueError("snapshot artifacts must use the exact canonical three-file inventory")
        return self


class TsinghuaAdapterAudit(FrozenModel):
    schema_version: Literal["tsinghua-adapter-audit-v1"]
    snapshot_id: str
    adapter_version: Literal["tsinghua-source-adapter-v1"]
    positive_recipe: Literal["tsv-positive-v1"]
    source_logical_row_count: int
    duplicate_expansion_row_count: int
    exposure_count: int
    user_count: int
    item_count: int
    max_expansion_rows_per_exposure: int
    positive_count: int
    explicit_negative_count: int
    passive_nonpositive_count: int
    title_available_count: int
    title_missing_count: int
    title_invalid_count: int
    title_conflict_count: int
    tags_available_count: int
    tags_invalid_count: int
    category_available_count: int
    category_paths_en_available_count: int
    category_paths_en_missing_count: int
    category_mapping_en_conflict_count: int
    category_mapping_en_unavailable_count: int
    category_mapping_missing_parent_count: int
    category_paths_cn_incomplete_item_count: int
    watch_time_exceeds_duration_count: int
    calendar_mismatch_exposure_count: int
    mutable_author_fans_item_count: int

    @field_validator("snapshot_id")
    @classmethod
    def _validate_snapshot_id(cls, value: str) -> str:
        return require_non_empty(value, "snapshot_id")

    @field_validator("*", mode="before")
    @classmethod
    def _validate_non_negative_counts(cls, value: object, info: ValidationInfo) -> object:
        if info.field_name.endswith("_count") and isinstance(value, int) and value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_partitions(self) -> "TsinghuaAdapterAudit":
        if (
            self.positive_count + self.explicit_negative_count + self.passive_nonpositive_count
            != self.exposure_count
        ):
            raise ValueError("interaction label counts must partition all exposures")
        if (
            self.title_available_count
            + self.title_missing_count
            + self.title_invalid_count
            + self.title_conflict_count
            != self.item_count
        ):
            raise ValueError("title audit counts must partition all items")
        if (
            self.category_paths_en_available_count + self.category_paths_en_missing_count
            != self.item_count
        ):
            raise ValueError("English category-path counts must partition all items")
        return self
