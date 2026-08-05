"""Strict records for item semantic prototypes and embedding artifacts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.domain.base import FrozenModel, JsonObject, require_non_empty, require_unique
from pave_rec.preprocessing.identity import validate_data_version
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key

SEMANTIC_TEXT_RECIPE = "tsv-item-semantic-text-v1"
EMBEDDING_RECIPE = "bge-m3-dense-v1"
SEMANTIC_BUILDER_VERSION = "p3-item-semantics-builder-v1"
SEMANTIC_VERSION_PATTERN = re.compile(r"^p3semantic-[0-9a-f]{64}$")
PROTOTYPE_ID_PATTERN = re.compile(r"^p3proto-[0-9a-f]{64}$")
VECTOR_SHARD_VERSION_PATTERN = re.compile(r"^p3vec-[0-9a-f]{64}$")


class ModelSnapshotFile(FrozenModel):
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
        if value <= 0:
            raise ValueError("model snapshot files must not be empty")
        return value

    @field_validator("checksum")
    @classmethod
    def _validate_checksum(cls, value: str) -> str:
        return require_sha256(value)


class BgeM3SnapshotManifest(FrozenModel):
    schema_version: Literal["bge-m3-model-snapshot-v1"]
    model_id: Literal["BAAI/bge-m3"]
    revision: Literal["5617a9f61b028005a4858fdac845db406aefb181"]
    files: tuple[ModelSnapshotFile, ...]

    @model_validator(mode="after")
    def _validate_files(self) -> "BgeM3SnapshotManifest":
        if not self.files:
            raise ValueError("BGE-M3 snapshot inventory must not be empty")
        paths = tuple(entry.relative_path for entry in self.files)
        require_unique(paths, "model snapshot paths")
        if paths != tuple(sorted(paths)):
            raise ValueError("model snapshot files must use canonical path order")
        return self


class ItemSemanticPrototype(FrozenModel):
    schema_version: Literal["p3-item-semantic-prototype-v1"]
    prototype_id: str
    item_id: str
    semantic_text: str
    semantic_text_sha256: str
    included_fields: tuple[Literal["title_cn", "tags", "category_paths_cn"], ...]
    embedding_ref: ResourceRef
    embedding_row_index: int
    provenance: JsonObject

    @field_validator("prototype_id")
    @classmethod
    def _validate_prototype_id(cls, value: str) -> str:
        if PROTOTYPE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("prototype_id must be p3proto-<64 lowercase hex>")
        return value

    @field_validator("item_id", "semantic_text")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("semantic_text_sha256")
    @classmethod
    def _validate_text_checksum(cls, value: str) -> str:
        return require_sha256(value)

    @field_validator("embedding_row_index")
    @classmethod
    def _validate_row(cls, value: int) -> int:
        if value < 0:
            raise ValueError("embedding_row_index must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_semantics(self) -> "ItemSemanticPrototype":
        canonical_order = ("title_cn", "tags", "category_paths_cn")
        expected = tuple(field for field in canonical_order if field in self.included_fields)
        if not self.included_fields or self.included_fields != expected:
            raise ValueError("included_fields must be a non-empty canonical subset")
        require_sha256(self.embedding_ref.checksum, "embedding_ref.checksum")
        validate_filesystem_key(self.embedding_ref.key)
        if VECTOR_SHARD_VERSION_PATTERN.fullmatch(self.embedding_ref.version) is None:
            raise ValueError("embedding_ref requires a p3vec version")
        return self


class EmbeddingIndexEntry(FrozenModel):
    schema_version: Literal["p3-semantic-embedding-index-entry-v1"]
    prototype_id: str
    item_id: str
    semantic_text_sha256: str
    embedding_ref: ResourceRef
    embedding_row_index: int
    dimension: Literal[1024]
    dtype: Literal["float32-le"]
    token_count: int
    was_truncated: bool

    @field_validator("prototype_id", "item_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        if info.field_name == "prototype_id" and PROTOTYPE_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("prototype_id must be p3proto-<64 lowercase hex>")
        return require_non_empty(value, info.field_name)

    @field_validator("semantic_text_sha256")
    @classmethod
    def _validate_checksum(cls, value: str) -> str:
        return require_sha256(value)

    @field_validator("embedding_row_index", "token_count")
    @classmethod
    def _validate_non_negative(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_embedding_ref(self) -> "EmbeddingIndexEntry":
        require_sha256(self.embedding_ref.checksum, "embedding_ref.checksum")
        validate_filesystem_key(self.embedding_ref.key)
        if VECTOR_SHARD_VERSION_PATTERN.fullmatch(self.embedding_ref.version) is None:
            raise ValueError("embedding_ref requires a p3vec version")
        return self


class ItemSemanticArtifactManifest(FrozenModel):
    schema_version: Literal["p3-item-semantic-artifact-manifest-v1"]
    semantic_version: str
    source_data_version: str
    source_release_ref: ResourceRef
    semantic_text_recipe: Literal["tsv-item-semantic-text-v1"]
    embedding_recipe: Literal["bge-m3-dense-v1"]
    model_id: Literal["BAAI/bge-m3"]
    model_revision: Literal["5617a9f61b028005a4858fdac845db406aefb181"]
    model_snapshot_checksum: str
    provider_package: Literal["FlagEmbedding"]
    provider_version: Literal["1.4.0"]
    pooling: Literal["official-dense-cls"]
    instruction: None
    max_tokens: Literal[1024]
    dimension: Literal[1024]
    dtype: Literal["float32-le"]
    normalization: Literal["l2-unit-v1"]
    semantic_items_ref: ResourceRef
    embedding_index_ref: ResourceRef
    embedding_shard_refs: tuple[ResourceRef, ...]
    counts: dict[str, int]

    @field_validator("semantic_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if SEMANTIC_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("semantic_version must be p3semantic-<64 lowercase hex>")
        return value

    @field_validator("source_data_version")
    @classmethod
    def _validate_source_version(cls, value: str) -> str:
        return validate_data_version(value)

    @field_validator("model_snapshot_checksum")
    @classmethod
    def _validate_snapshot_checksum(cls, value: str) -> str:
        return require_sha256(value)

    @model_validator(mode="after")
    def _validate_refs_and_counts(self) -> "ItemSemanticArtifactManifest":
        if (
            self.source_release_ref.version != self.source_data_version
            or self.source_release_ref.key != f"releases/{self.source_data_version}.json"
        ):
            raise ValueError("source release ref/data version mismatch")
        refs = (
            self.semantic_items_ref,
            self.embedding_index_ref,
            *self.embedding_shard_refs,
        )
        for ref in refs:
            require_sha256(ref.checksum)
            validate_filesystem_key(ref.key)
        for ref, expected_name in (
            (self.semantic_items_ref, "semantic_items.jsonl"),
            (self.embedding_index_ref, "embedding_index.jsonl"),
        ):
            if (
                ref.version != self.semantic_version
                or ref.key != f"bundles/{self.semantic_version}/{expected_name}"
                or ref.store != self.semantic_items_ref.store
            ):
                raise ValueError("semantic singleton ref identity mismatch")
        if not self.embedding_shard_refs:
            raise ValueError("semantic artifact requires embedding shards")
        expected_counts = {
            "source_items",
            "semantic_items",
            "missing_semantics",
            "unique_semantic_texts",
            "embedding_shards",
            "truncated_texts",
        }
        if set(self.counts) != expected_counts or any(value < 0 for value in self.counts.values()):
            raise ValueError("semantic artifact count inventory mismatch")
        if (
            self.counts["semantic_items"] + self.counts["missing_semantics"]
            != self.counts["source_items"]
        ):
            raise ValueError("semantic/missing counts must partition source items")
        if self.counts["embedding_shards"] != len(self.embedding_shard_refs):
            raise ValueError("semantic shard count mismatch")
        if self.counts["unique_semantic_texts"] > self.counts["semantic_items"]:
            raise ValueError("unique semantic text count exceeds semantic item count")
        if self.counts["truncated_texts"] > self.counts["unique_semantic_texts"]:
            raise ValueError("truncated text count exceeds unique semantic text count")
        if len({(ref.store, ref.key) for ref in self.embedding_shard_refs}) != len(
            self.embedding_shard_refs
        ):
            raise ValueError("semantic embedding shard refs must be unique")
        for ref in self.embedding_shard_refs:
            if (
                ref.store != self.semantic_items_ref.store
                or VECTOR_SHARD_VERSION_PATTERN.fullmatch(ref.version) is None
                or ref.key != f"embedding-shards/{ref.version.removeprefix('p3vec-')}.f32"
            ):
                raise ValueError("semantic embedding shard ref identity mismatch")
        return self
