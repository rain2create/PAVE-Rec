"""Authoritative P3-06 exact-prefix Memory build lifecycle."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from pathlib import Path

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError
from pave_rec.phase3.derived import load_derived_dataset
from pave_rec.phase3.input_bundle import history_prefix_checksum
from pave_rec.phase3.semantics import load_item_semantics
from pave_rec.preprocessing.paths import FilesystemPathResolver
from pave_rec.stores.release import ReleaseLoader

from .artifact import (
    VECTOR_BYTES,
    FilesystemMemoryArtifactPublisher,
    build_memory_artifact_plan,
)
from .config import load_phase3_memory_config
from .engine import MemoryObservation, build_memory_snapshot


@dataclass(frozen=True)
class MemoryBuildResult:
    execution_id: str
    outcome: str
    artifact_version: str
    manifest_ref: ResourceRef
    snapshot_count: int
    semantic_observation_count: int
    active_long_track_count: int
    pending_track_count: int
    inactive_long_track_count: int
    promotion_count: int


def _execution_id(config_path: Path, derived_ref: ResourceRef, semantic_ref: ResourceRef) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "config_path": config_path.as_posix(),
                "derived_artifact_ref": derived_ref.model_dump(mode="json", exclude_none=False),
                "semantic_artifact_ref": semantic_ref.model_dump(mode="json", exclude_none=False),
            },
            pretty=False,
        )
    ).hexdigest()[:16]
    return f"p3-memory-{digest}"


class _SemanticVectorCache:
    def __init__(self, resolver: FilesystemPathResolver) -> None:
        self._resolver = resolver
        self._payloads: dict[tuple[str, str, str, str], bytes] = {}

    def load(self, ref: ResourceRef, row_index: int) -> tuple[float, ...]:
        identity = (ref.store, ref.key, ref.version, ref.checksum or "")
        payload = self._payloads.get(identity)
        if payload is None:
            payload = self._resolver.read_verified_bytes(ref)
            if len(payload) % VECTOR_BYTES:
                raise ArtifactIntegrityError("semantic embedding shard size is invalid")
            self._payloads[identity] = payload
        start = row_index * VECTOR_BYTES
        end = start + VECTOR_BYTES
        if row_index < 0 or end > len(payload):
            raise ArtifactIntegrityError("semantic embedding row is outside its shard")
        vector = struct.unpack("<1024f", payload[start:end])
        if any(not math.isfinite(value) for value in vector):
            raise ArtifactIntegrityError("semantic embedding contains non-finite values")
        norm = math.sqrt(math.fsum(value * value for value in vector))
        if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
            raise ArtifactIntegrityError("semantic embedding is not L2-normalized")
        return vector


def build_memory_from_config(
    config_path: str | Path,
    *,
    execution_id: str | None = None,
) -> MemoryBuildResult:
    loaded = load_phase3_memory_config(config_path)
    config = loaded.config
    actual_execution_id = execution_id or _execution_id(
        loaded.config_path.relative_to(loaded.project_root),
        config.derived_artifact_ref,
        config.semantic_artifact_ref,
    )
    release = ReleaseLoader(loaded.root_registry).load(config.source_release_ref)
    resolver = FilesystemPathResolver(loaded.root_registry)
    derived_manifest, derived = load_derived_dataset(resolver, config.derived_artifact_ref)
    semantics = load_item_semantics(resolver, config.semantic_artifact_ref)
    if (
        derived_manifest.source_release_ref != config.source_release_ref
        or semantics.manifest.source_release_ref != config.source_release_ref
        or release.data_version != derived_manifest.source_data_version
        or release.data_version != semantics.manifest.source_data_version
    ):
        raise ArtifactIntegrityError("memory source/derived/semantic artifact closure mismatch")
    prototypes = {prototype.item_id: prototype for prototype in semantics.prototypes}
    if len(prototypes) != len(semantics.prototypes):
        raise ArtifactIntegrityError("semantic artifact contains duplicate item prototypes")
    vector_cache = _SemanticVectorCache(resolver)
    snapshots = []
    for split in derived.user_splits:
        for target in (split.validation_target, split.test_target):
            ordered_item_ids = tuple(event.item_id for event in target.history)
            observations = []
            for event in target.history:
                prototype = prototypes.get(event.item_id)
                if prototype is None:
                    continue
                observations.append(
                    MemoryObservation(
                        item_id=event.item_id,
                        prototype_id=prototype.prototype_id,
                        semantic_text=prototype.semantic_text,
                        embedding_ref=prototype.embedding_ref,
                        embedding_row_index=prototype.embedding_row_index,
                        interaction_index=event.source_interaction_index,
                        occurred_at_ms=event.occurred_at_ms,
                        vector=vector_cache.load(
                            prototype.embedding_ref, prototype.embedding_row_index
                        ),
                    )
                )
            snapshots.append(
                build_memory_snapshot(
                    user_id=split.user_id,
                    cutoff_identity=target.cutoff_identity,
                    history_projection_checksum=history_prefix_checksum(
                        split.user_id, ordered_item_ids
                    ),
                    observations=tuple(observations),
                )
            )
    ordered_snapshots = tuple(
        sorted(
            snapshots,
            key=lambda snapshot: (
                snapshot.user_id,
                snapshot.cutoff_identity,
                snapshot.history_projection_checksum,
            ),
        )
    )
    plan = build_memory_artifact_plan(
        output_root_id=config.output_root_id,
        source_release_ref=config.source_release_ref,
        derived_artifact_ref=config.derived_artifact_ref,
        semantic_artifact_ref=config.semantic_artifact_ref,
        snapshots=ordered_snapshots,
    )
    publication = FilesystemMemoryArtifactPublisher(loaded.root_registry).publish(
        plan, execution_id=actual_execution_id
    )
    counts = plan.manifest.counts
    return MemoryBuildResult(
        execution_id=actual_execution_id,
        outcome=publication.outcome,
        artifact_version=plan.artifact_version,
        manifest_ref=publication.manifest_ref,
        snapshot_count=counts["snapshots"],
        semantic_observation_count=counts["semantic_observations"],
        active_long_track_count=counts["active_long_tracks"],
        pending_track_count=counts["pending_tracks"],
        inactive_long_track_count=counts["inactive_long_tracks"],
        promotion_count=counts["promotions"],
    )
