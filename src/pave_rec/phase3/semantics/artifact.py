"""Deterministic item-semantic artifact construction, publication, and loading."""

from __future__ import annotations

import hashlib
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import (
    ArtifactIntegrityError,
    ArtifactPublicationError,
    DatasetValidationError,
    ResourceResolutionError,
)
from pave_rec.preprocessing.codecs import (
    decode_canonical_json,
    decode_jsonl,
    encode_json,
    encode_jsonl,
)
from pave_rec.preprocessing.paths import FilesystemPathResolver, RootRegistry
from pave_rec.preprocessing.publisher import publication_staging_key

from .models import (
    EMBEDDING_RECIPE,
    SEMANTIC_BUILDER_VERSION,
    SEMANTIC_TEXT_RECIPE,
    EmbeddingIndexEntry,
    ItemSemanticArtifactManifest,
    ItemSemanticPrototype,
)
from .provider import EmbeddingResult
from .text import SemanticTextSpec

SHARD_ROW_COUNT = 4096
VECTOR_BYTES = 1024 * 4


def _checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _vector_payload(vectors: tuple[EmbeddingResult, ...]) -> bytes:
    payload = b"".join(struct.pack("<1024f", *result.vector) for result in vectors)
    if len(payload) != len(vectors) * VECTOR_BYTES:
        raise ValueError("semantic vector shard byte size mismatch")
    return payload


@dataclass(frozen=True)
class ItemSemanticArtifactPlan:
    semantic_version: str
    output_root_id: str
    manifest: ItemSemanticArtifactManifest
    manifest_ref: ResourceRef
    prototypes: tuple[ItemSemanticPrototype, ...]
    embedding_index: tuple[EmbeddingIndexEntry, ...]
    bundle_files: tuple[tuple[str, bytes], ...]
    shard_files: tuple[tuple[ResourceRef, bytes], ...]


@dataclass(frozen=True)
class SemanticPublicationResult:
    outcome: Literal["created", "reused"]
    manifest_ref: ResourceRef


@dataclass(frozen=True)
class LoadedItemSemantics:
    manifest: ItemSemanticArtifactManifest
    prototypes: tuple[ItemSemanticPrototype, ...]
    embedding_index: tuple[EmbeddingIndexEntry, ...]


def build_item_semantic_artifact_plan(
    *,
    output_root_id: str,
    source_data_version: str,
    source_release_ref: ResourceRef,
    source_item_count: int,
    specs: tuple[SemanticTextSpec, ...],
    embeddings_by_text_checksum: Mapping[str, EmbeddingResult],
    model_snapshot_checksum: str,
) -> ItemSemanticArtifactPlan:
    item_ids = tuple(spec.item_id for spec in specs)
    if item_ids != tuple(sorted(item_ids)) or len(item_ids) != len(set(item_ids)):
        raise ValueError("semantic specs require unique canonical item order")
    text_checksums = tuple(sorted({spec.semantic_text_sha256 for spec in specs}))
    if set(text_checksums) != set(embeddings_by_text_checksum):
        raise ValueError("semantic embedding coverage mismatch")
    shard_files: list[tuple[ResourceRef, bytes]] = []
    locations: dict[str, tuple[ResourceRef, int]] = {}
    for start in range(0, len(text_checksums), SHARD_ROW_COUNT):
        shard_keys = text_checksums[start : start + SHARD_ROW_COUNT]
        payload = _vector_payload(tuple(embeddings_by_text_checksum[key] for key in shard_keys))
        digest = hashlib.sha256(payload).hexdigest()
        version = f"p3vec-{digest}"
        ref = ResourceRef(
            store=output_root_id,
            key=f"embedding-shards/{digest}.f32",
            version=version,
            checksum=f"sha256:{digest}",
        )
        shard_files.append((ref, payload))
        for row_index, text_checksum in enumerate(shard_keys):
            locations[text_checksum] = (ref, row_index)
    prototypes: list[ItemSemanticPrototype] = []
    index: list[EmbeddingIndexEntry] = []
    for spec in specs:
        embedding_ref, row_index = locations[spec.semantic_text_sha256]
        result = embeddings_by_text_checksum[spec.semantic_text_sha256]
        prototype = ItemSemanticPrototype(
            schema_version="p3-item-semantic-prototype-v1",
            prototype_id=spec.prototype_id,
            item_id=spec.item_id,
            semantic_text=spec.semantic_text,
            semantic_text_sha256=spec.semantic_text_sha256,
            included_fields=spec.included_fields,
            embedding_ref=embedding_ref,
            embedding_row_index=row_index,
            provenance={
                "source_data_version": source_data_version,
                "semantic_text_recipe": SEMANTIC_TEXT_RECIPE,
                "embedding_recipe": EMBEDDING_RECIPE,
            },
        )
        prototypes.append(prototype)
        index.append(
            EmbeddingIndexEntry(
                schema_version="p3-semantic-embedding-index-entry-v1",
                prototype_id=spec.prototype_id,
                item_id=spec.item_id,
                semantic_text_sha256=spec.semantic_text_sha256,
                embedding_ref=embedding_ref,
                embedding_row_index=row_index,
                dimension=1024,
                dtype="float32-le",
                token_count=result.token_count,
                was_truncated=result.was_truncated,
            )
        )
    semantic_payload = encode_jsonl(tuple(prototypes))
    index_payload = encode_jsonl(tuple(index))
    counts = {
        "source_items": source_item_count,
        "semantic_items": len(specs),
        "missing_semantics": source_item_count - len(specs),
        "unique_semantic_texts": len(text_checksums),
        "embedding_shards": len(shard_files),
        "truncated_texts": sum(
            result.was_truncated for result in embeddings_by_text_checksum.values()
        ),
    }
    identity = {
        "identity_schema_version": "p3-item-semantic-artifact-identity-v1",
        "builder_version": SEMANTIC_BUILDER_VERSION,
        "source_data_version": source_data_version,
        "source_release_ref": source_release_ref.model_dump(mode="json", exclude_none=False),
        "semantic_text_recipe": SEMANTIC_TEXT_RECIPE,
        "embedding_contract": {
            "recipe": EMBEDDING_RECIPE,
            "model_id": "BAAI/bge-m3",
            "revision": "5617a9f61b028005a4858fdac845db406aefb181",
            "snapshot_checksum": model_snapshot_checksum,
            "provider_package": "FlagEmbedding",
            "provider_version": "1.4.0",
            "pooling": "official-dense-cls",
            "instruction": None,
            "max_tokens": 1024,
            "dimension": 1024,
            "dtype": "float32-le",
            "normalization": "l2-unit-v1",
        },
        "payload_checksums": {
            "semantic_items.jsonl": _checksum(semantic_payload),
            "embedding_index.jsonl": _checksum(index_payload),
            **{ref.key: ref.checksum for ref, _ in shard_files},
        },
        "counts": counts,
    }
    semantic_version = (
        "p3semantic-" + hashlib.sha256(canonical_json_bytes(identity, pretty=False)).hexdigest()
    )
    semantic_ref = ResourceRef(
        store=output_root_id,
        key=f"bundles/{semantic_version}/semantic_items.jsonl",
        version=semantic_version,
        checksum=_checksum(semantic_payload),
    )
    index_ref = ResourceRef(
        store=output_root_id,
        key=f"bundles/{semantic_version}/embedding_index.jsonl",
        version=semantic_version,
        checksum=_checksum(index_payload),
    )
    manifest = ItemSemanticArtifactManifest(
        schema_version="p3-item-semantic-artifact-manifest-v1",
        semantic_version=semantic_version,
        source_data_version=source_data_version,
        source_release_ref=source_release_ref,
        semantic_text_recipe=SEMANTIC_TEXT_RECIPE,
        embedding_recipe=EMBEDDING_RECIPE,
        model_id="BAAI/bge-m3",
        model_revision="5617a9f61b028005a4858fdac845db406aefb181",
        model_snapshot_checksum=model_snapshot_checksum,
        provider_package="FlagEmbedding",
        provider_version="1.4.0",
        pooling="official-dense-cls",
        instruction=None,
        max_tokens=1024,
        dimension=1024,
        dtype="float32-le",
        normalization="l2-unit-v1",
        semantic_items_ref=semantic_ref,
        embedding_index_ref=index_ref,
        embedding_shard_refs=tuple(ref for ref, _ in shard_files),
        counts=counts,
    )
    manifest_payload = encode_json(manifest)
    manifest_ref = ResourceRef(
        store=output_root_id,
        key=f"bundles/{semantic_version}/manifest.json",
        version=semantic_version,
        checksum=_checksum(manifest_payload),
    )
    return ItemSemanticArtifactPlan(
        semantic_version=semantic_version,
        output_root_id=output_root_id,
        manifest=manifest,
        manifest_ref=manifest_ref,
        prototypes=tuple(prototypes),
        embedding_index=tuple(index),
        bundle_files=tuple(
            sorted(
                {
                    "embedding_index.jsonl": index_payload,
                    "manifest.json": manifest_payload,
                    "semantic_items.jsonl": semantic_payload,
                }.items()
            )
        ),
        shard_files=tuple(shard_files),
    )


class FilesystemItemSemanticPublisher:
    def __init__(self, registry: RootRegistry) -> None:
        self._resolver = FilesystemPathResolver(registry)

    @staticmethod
    def _verify_bundle(plan: ItemSemanticArtifactPlan, directory: Path) -> None:
        expected = {name for name, _ in plan.bundle_files}
        try:
            actual = {
                path.relative_to(directory).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
            }
        except OSError as exc:
            raise ArtifactIntegrityError("cannot inventory semantic artifact bundle") from exc
        if actual != expected:
            raise ArtifactIntegrityError("semantic artifact bundle inventory mismatch")
        for name, payload in plan.bundle_files:
            try:
                actual_payload = directory.joinpath(name).read_bytes()
            except OSError as exc:
                raise ArtifactIntegrityError(f"cannot read semantic bundle file: {name}") from exc
            if actual_payload != payload:
                raise ArtifactIntegrityError(f"semantic bundle file mismatch: {name}")

    def _publish_shard(self, ref: ResourceRef, payload: bytes, staged: Path) -> None:
        target = self._resolver.resolve_new_path(ref.store, ref.key)
        if target.exists():
            try:
                actual = target.read_bytes()
            except OSError as exc:
                raise ArtifactIntegrityError(
                    "cannot verify existing semantic vector shard"
                ) from exc
            if actual != payload:
                raise ArtifactIntegrityError("existing semantic vector shard is corrupt")
            try:
                staged.unlink()
            except OSError as exc:
                raise ArtifactPublicationError(
                    "cannot retire verified staged vector shard"
                ) from exc
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            staged.rename(target)
        except OSError as exc:
            if target.exists() and target.read_bytes() == payload:
                return
            raise ArtifactPublicationError("cannot publish semantic vector shard") from exc

    def publish(
        self,
        plan: ItemSemanticArtifactPlan,
        *,
        execution_id: str,
    ) -> SemanticPublicationResult:
        target = self._resolver.resolve_new_path(
            plan.output_root_id,
            f"bundles/{plan.semantic_version}",
        )
        if target.exists():
            self._verify_bundle(plan, target)
            for ref, payload in plan.shard_files:
                try:
                    actual = self._resolver.resolve_new_path(ref.store, ref.key).read_bytes()
                except OSError as exc:
                    raise ArtifactIntegrityError("cannot verify semantic shard reuse") from exc
                if actual != payload:
                    raise ArtifactIntegrityError("semantic shard reuse mismatch")
            return SemanticPublicationResult("reused", plan.manifest_ref)
        stage = self._resolver.resolve_new_path(
            plan.output_root_id,
            publication_staging_key(plan.output_root_id, plan.semantic_version, execution_id),
        )
        vector_stage = stage.joinpath(".__vectors")
        try:
            stage.mkdir(parents=True, exist_ok=False)
            vector_stage.mkdir()
            for name, payload in plan.bundle_files:
                with stage.joinpath(name).open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            for index, (ref, payload) in enumerate(plan.shard_files):
                staged = vector_stage.joinpath(f"{index:05d}.f32")
                with staged.open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._publish_shard(ref, payload, staged)
            self._verify_bundle(plan, stage)
            target.parent.mkdir(parents=True, exist_ok=True)
            stage.rename(target)
        except ArtifactIntegrityError:
            raise
        except OSError as exc:
            if target.exists():
                self._verify_bundle(plan, target)
                return SemanticPublicationResult("reused", plan.manifest_ref)
            raise ArtifactPublicationError("cannot publish item-semantic artifact") from exc
        self._verify_bundle(plan, target)
        return SemanticPublicationResult("created", plan.manifest_ref)


def _decode_jsonl_exact(payload: bytes, model_type, logical_name: str):
    try:
        records = decode_jsonl(payload, model_type, logical_name=logical_name)
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError(f"invalid {logical_name}") from exc
    if encode_jsonl(records) != payload:
        raise ArtifactIntegrityError(f"non-canonical {logical_name}")
    return records


def load_item_semantics(
    resolver: FilesystemPathResolver,
    manifest_ref: ResourceRef,
) -> LoadedItemSemantics:
    try:
        manifest_payload = resolver.read_verified_bytes(manifest_ref)
        manifest = decode_canonical_json(
            manifest_payload,
            ItemSemanticArtifactManifest,
            logical_name="item semantic manifest",
        )
        semantic_payload = resolver.read_verified_bytes(manifest.semantic_items_ref)
        index_payload = resolver.read_verified_bytes(manifest.embedding_index_ref)
    except (DatasetValidationError, ResourceResolutionError) as exc:
        raise ArtifactIntegrityError("cannot load exact item semantic artifact") from exc
    if (
        manifest.semantic_version != manifest_ref.version
        or manifest_ref.key != f"bundles/{manifest.semantic_version}/manifest.json"
    ):
        raise ArtifactIntegrityError("item semantic manifest identity mismatch")
    prototypes = _decode_jsonl_exact(
        semantic_payload,
        ItemSemanticPrototype,
        "item semantic prototypes",
    )
    index = _decode_jsonl_exact(
        index_payload,
        EmbeddingIndexEntry,
        "semantic embedding index",
    )
    prototype_projection = tuple(
        (
            entry.prototype_id,
            entry.item_id,
            entry.semantic_text_sha256,
            entry.embedding_ref,
            entry.embedding_row_index,
        )
        for entry in prototypes
    )
    index_projection = tuple(
        (
            entry.prototype_id,
            entry.item_id,
            entry.semantic_text_sha256,
            entry.embedding_ref,
            entry.embedding_row_index,
        )
        for entry in index
    )
    if prototype_projection != index_projection:
        raise ArtifactIntegrityError("semantic prototype/index coverage mismatch")
    if len(prototypes) != manifest.counts["semantic_items"]:
        raise ArtifactIntegrityError("semantic manifest count mismatch")
    return LoadedItemSemantics(manifest, prototypes, index)


def load_prototype_embedding(
    resolver: FilesystemPathResolver,
    prototype: ItemSemanticPrototype,
) -> tuple[float, ...]:
    try:
        payload = resolver.read_verified_bytes(prototype.embedding_ref)
    except ResourceResolutionError as exc:
        raise ArtifactIntegrityError("cannot verify prototype embedding shard") from exc
    if len(payload) % VECTOR_BYTES != 0:
        raise ArtifactIntegrityError("semantic embedding shard size is invalid")
    start = prototype.embedding_row_index * VECTOR_BYTES
    end = start + VECTOR_BYTES
    if end > len(payload):
        raise ArtifactIntegrityError("prototype embedding row is outside its shard")
    vector = struct.unpack("<1024f", payload[start:end])
    if any(not math.isfinite(value) for value in vector):
        raise ArtifactIntegrityError("prototype embedding contains non-finite values")
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
        raise ArtifactIntegrityError("prototype embedding is not L2-normalized")
    return vector
