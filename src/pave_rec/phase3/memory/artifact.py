"""Immutable construction, publication, and exact loading of Memory snapshots."""

from __future__ import annotations

import hashlib
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pave_rec.domain import PreferenceMatchType, ResourceRef, UserMemoryView
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, ArtifactPublicationError, DatasetValidationError
from pave_rec.preprocessing.codecs import (
    decode_canonical_json,
    decode_jsonl,
    encode_json,
    encode_jsonl,
)
from pave_rec.preprocessing.paths import FilesystemPathResolver, RootRegistry
from pave_rec.preprocessing.publisher import publication_staging_key

from .engine import (
    EMA_ETA,
    INACTIVE_STRENGTH,
    MATCH_THRESHOLD,
    MAX_PROJECTED_LONG,
    MEMORY_RECIPE,
    PERSISTENCE_SATURATION,
    PROMOTION_DISTINCT_TIMES,
    RECENCY_HALF_LIFE_DAYS,
    RECENT_SHORT_COUNT,
    BuiltMemorySnapshot,
    MemoryTrack,
)
from .models import (
    MemoryArtifactManifest,
    MemorySnapshotIndexEntry,
    MemoryStateRecord,
    MemorySupportRecord,
    MemoryTrackRecord,
    MemoryViewRecord,
)

VECTOR_DIMENSION = 1024
VECTOR_BYTES = VECTOR_DIMENSION * 4


def _checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _record_checksum(record) -> str:
    return _checksum(canonical_json_bytes(record, pretty=False))


def _pack_vectors(vectors: tuple[tuple[float, ...], ...]) -> bytes:
    if any(len(vector) != VECTOR_DIMENSION for vector in vectors):
        raise ValueError("memory artifact requires 1024-dimensional centroids")
    return b"".join(struct.pack("<1024f", *vector) for vector in vectors)


@dataclass(frozen=True)
class MemoryArtifactPlan:
    artifact_version: str
    output_root_id: str
    manifest: MemoryArtifactManifest
    manifest_ref: ResourceRef
    states: tuple[MemoryStateRecord, ...]
    views: tuple[MemoryViewRecord, ...]
    snapshot_index: tuple[MemorySnapshotIndexEntry, ...]
    files: tuple[tuple[ResourceRef, bytes], ...]


@dataclass(frozen=True)
class MemoryPublicationResult:
    outcome: Literal["created", "reused"]
    manifest_ref: ResourceRef


@dataclass(frozen=True)
class LoadedMemoryArtifact:
    manifest: MemoryArtifactManifest
    states: tuple[MemoryStateRecord, ...]
    views: tuple[MemoryViewRecord, ...]
    snapshot_index: tuple[MemorySnapshotIndexEntry, ...]


def _snapshot_identity(snapshot: BuiltMemorySnapshot) -> dict[str, object]:
    return {
        "user_id": snapshot.user_id,
        "cutoff_identity": snapshot.cutoff_identity,
        "history_projection_checksum": snapshot.history_projection_checksum,
        "updated_at_ms": snapshot.updated_at_ms,
        "observed_count": snapshot.observed_count,
        "promotion_count": snapshot.promotion_count,
        "tracks": [
            {
                "atom_id": track.atom_id,
                "centroid_checksum": _checksum(_pack_vectors((track.centroid,))),
                "support_events": [support.event_identity for support in track.supports],
            }
            for track in (
                *snapshot.active_long_tracks,
                *snapshot.unprojected_long_tracks,
                *snapshot.inactive_long_tracks,
                *snapshot.pending_tracks,
            )
        ],
        "short_event_indexes": [
            short.observation.interaction_index for short in snapshot.short_atoms
        ],
    }


def _track_state(snapshot: BuiltMemorySnapshot, track: MemoryTrack) -> str:
    if track.inactive:
        return "inactive"
    stable = any(
        match.long_atom_id == track.atom_id and match.classification is PreferenceMatchType.STABLE
        for match in snapshot.matches
    )
    return "stable" if stable else "fading"


def build_memory_artifact_plan(
    *,
    output_root_id: str,
    source_release_ref: ResourceRef,
    derived_artifact_ref: ResourceRef,
    semantic_artifact_ref: ResourceRef,
    snapshots: tuple[BuiltMemorySnapshot, ...],
) -> MemoryArtifactPlan:
    identities = tuple(
        (snapshot.user_id, snapshot.cutoff_identity, snapshot.history_projection_checksum)
        for snapshot in snapshots
    )
    if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
        raise ValueError("memory snapshots require unique canonical user/cutoff order")
    identity = {
        "identity_schema_version": "p3-memory-artifact-identity-v1",
        "source_release_ref": source_release_ref.model_dump(mode="json", exclude_none=False),
        "derived_artifact_ref": derived_artifact_ref.model_dump(mode="json", exclude_none=False),
        "semantic_artifact_ref": semantic_artifact_ref.model_dump(mode="json", exclude_none=False),
        "recipe": {
            "id": MEMORY_RECIPE,
            "recent_short_count": RECENT_SHORT_COUNT,
            "max_projected_long": MAX_PROJECTED_LONG,
            "match_threshold": MATCH_THRESHOLD,
            "ema_eta": EMA_ETA,
            "promotion_distinct_times": PROMOTION_DISTINCT_TIMES,
            "persistence_saturation": PERSISTENCE_SATURATION,
            "recency_half_life_days": RECENCY_HALF_LIFE_DAYS,
            "inactive_strength": INACTIVE_STRENGTH,
        },
        "snapshots": [_snapshot_identity(snapshot) for snapshot in snapshots],
    }
    artifact_version = (
        "p3memoryartifact-"
        + hashlib.sha256(canonical_json_bytes(identity, pretty=False)).hexdigest()
    )
    prefix = f"bundles/{artifact_version}"

    all_tracks: list[tuple[BuiltMemorySnapshot, MemoryTrack, Literal["long", "pending"]]] = []
    for snapshot in snapshots:
        all_tracks.extend((snapshot, track, "long") for track in snapshot.active_long_tracks)
        all_tracks.extend((snapshot, track, "long") for track in snapshot.unprojected_long_tracks)
        all_tracks.extend((snapshot, track, "long") for track in snapshot.inactive_long_tracks)
        all_tracks.extend((snapshot, track, "pending") for track in snapshot.pending_tracks)
    vector_payload = _pack_vectors(tuple(track.centroid for _, track, _ in all_tracks))
    vector_ref = (
        ResourceRef(
            store=output_root_id,
            key=f"{prefix}/memory_embeddings.f32",
            version=artifact_version,
            checksum=_checksum(vector_payload),
        )
        if all_tracks
        else None
    )
    row_by_identity = {
        (id(snapshot), track.atom_id): row for row, (snapshot, track, _) in enumerate(all_tracks)
    }

    matrix_offsets: dict[int, int] = {}
    matrix_values: list[float] = []
    for snapshot in snapshots:
        if snapshot.active_long_tracks and snapshot.short_atoms:
            matrix_offsets[id(snapshot)] = len(matrix_values)
            matrix_values.extend(value for row in snapshot.similarity_matrix for value in row)
    matrix_payload = (
        struct.pack(f"<{len(matrix_values)}f", *matrix_values) if matrix_values else b""
    )
    matrix_ref = (
        ResourceRef(
            store=output_root_id,
            key=f"{prefix}/similarity_matrices.f32",
            version=artifact_version,
            checksum=_checksum(matrix_payload),
        )
        if matrix_values
        else None
    )

    states: list[MemoryStateRecord] = []
    views: list[MemoryViewRecord] = []
    index: list[MemorySnapshotIndexEntry] = []
    for line_index, snapshot in enumerate(snapshots):
        snapshot_id = (
            "p3snapshot-"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "artifact_version": artifact_version,
                        "user_id": snapshot.user_id,
                        "cutoff_identity": snapshot.cutoff_identity,
                        "history_projection_checksum": snapshot.history_projection_checksum,
                    },
                    pretty=False,
                )
            ).hexdigest()
        )
        memory_version = (
            "p3memory-"
            + hashlib.sha256(
                canonical_json_bytes(
                    {"artifact_version": artifact_version, "snapshot_id": snapshot_id},
                    pretty=False,
                )
            ).hexdigest()
        )
        records: list[MemoryTrackRecord] = []
        for track, kind in (
            *((track, "long") for track in snapshot.active_long_tracks),
            *((track, "long") for track in snapshot.unprojected_long_tracks),
            *((track, "long") for track in snapshot.inactive_long_tracks),
            *((track, "pending") for track in snapshot.pending_tracks),
        ):
            if vector_ref is None:
                raise ValueError("memory tracks require a centroid shard")
            records.append(
                MemoryTrackRecord(
                    atom_id=track.atom_id,
                    kind=kind,
                    state="emerging" if kind == "pending" else _track_state(snapshot, track),
                    centroid_ref=vector_ref,
                    centroid_row_index=row_by_identity[(id(snapshot), track.atom_id)],
                    medoid_prototype_id=track.medoid.prototype_id,
                    medoid_text=track.medoid.semantic_text,
                    strength=track.strength,
                    persistence=track.persistence,
                    supports=tuple(
                        MemorySupportRecord(
                            item_id=support.item_id,
                            prototype_id=support.prototype_id,
                            source_interaction_index=support.interaction_index,
                            occurred_at_ms=support.occurred_at_ms,
                        )
                        for support in track.supports
                    ),
                )
            )
        state = MemoryStateRecord(
            schema_version="p3-memory-state-v1",
            snapshot_id=snapshot_id,
            memory_version=memory_version,
            user_id=snapshot.user_id,
            cutoff_identity=snapshot.cutoff_identity,
            history_projection_checksum=snapshot.history_projection_checksum,
            updated_at_ms=snapshot.updated_at_ms,
            tracks=tuple(records),
            observed_semantic_count=snapshot.observed_count,
            promotion_count=snapshot.promotion_count,
        )
        view = snapshot.to_view(
            memory_version=memory_version,
            long_embedding_ref=vector_ref if snapshot.active_long_tracks else None,
            similarity_matrix_ref=matrix_ref
            if snapshot.active_long_tracks and snapshot.short_atoms
            else None,
            semantic_artifact_ref=semantic_artifact_ref,
            derived_artifact_ref=derived_artifact_ref,
        )
        if matrix_ref is not None and snapshot.active_long_tracks and snapshot.short_atoms:
            view = view.model_copy(
                update={
                    "metadata": {
                        **view.metadata,
                        "similarity_matrix_float_offset": matrix_offsets[id(snapshot)],
                    }
                }
            )
        view_record = MemoryViewRecord(
            schema_version="p3-memory-view-record-v1",
            snapshot_id=snapshot_id,
            user_id=snapshot.user_id,
            cutoff_identity=snapshot.cutoff_identity,
            history_projection_checksum=snapshot.history_projection_checksum,
            view=view,
        )
        states.append(state)
        views.append(view_record)
        index.append(
            MemorySnapshotIndexEntry(
                schema_version="p3-memory-snapshot-index-entry-v1",
                snapshot_id=snapshot_id,
                memory_version=memory_version,
                user_id=snapshot.user_id,
                cutoff_identity=snapshot.cutoff_identity,
                history_projection_checksum=snapshot.history_projection_checksum,
                state_line_index=line_index,
                state_record_checksum=_record_checksum(state),
                view_line_index=line_index,
                view_record_checksum=_record_checksum(view_record),
            )
        )

    state_payload = encode_jsonl(tuple(states))
    view_payload = encode_jsonl(tuple(views))
    index_payload = encode_jsonl(tuple(index))
    refs = {
        "memory_states.jsonl": ResourceRef(
            store=output_root_id,
            key=f"{prefix}/memory_states.jsonl",
            version=artifact_version,
            checksum=_checksum(state_payload),
        ),
        "memory_views.jsonl": ResourceRef(
            store=output_root_id,
            key=f"{prefix}/memory_views.jsonl",
            version=artifact_version,
            checksum=_checksum(view_payload),
        ),
        "snapshot_index.jsonl": ResourceRef(
            store=output_root_id,
            key=f"{prefix}/snapshot_index.jsonl",
            version=artifact_version,
            checksum=_checksum(index_payload),
        ),
    }
    counts = {
        "active_long_tracks": sum(len(snapshot.active_long_tracks) for snapshot in snapshots),
        "inactive_long_tracks": sum(len(snapshot.inactive_long_tracks) for snapshot in snapshots),
        "matrix_float_count": len(matrix_values),
        "pending_tracks": sum(len(snapshot.pending_tracks) for snapshot in snapshots),
        "promotions": sum(snapshot.promotion_count for snapshot in snapshots),
        "semantic_observations": sum(snapshot.observed_count for snapshot in snapshots),
        "snapshots": len(snapshots),
        "unprojected_long_tracks": sum(
            len(snapshot.unprojected_long_tracks) for snapshot in snapshots
        ),
    }
    manifest = MemoryArtifactManifest(
        schema_version="p3-memory-artifact-manifest-v1",
        artifact_version=artifact_version,
        source_release_ref=source_release_ref,
        derived_artifact_ref=derived_artifact_ref,
        semantic_artifact_ref=semantic_artifact_ref,
        memory_recipe=MEMORY_RECIPE,
        recent_short_count=RECENT_SHORT_COUNT,
        max_projected_long=MAX_PROJECTED_LONG,
        match_threshold=MATCH_THRESHOLD,
        ema_eta=EMA_ETA,
        promotion_distinct_times=PROMOTION_DISTINCT_TIMES,
        persistence_saturation=PERSISTENCE_SATURATION,
        recency_half_life_days=RECENCY_HALF_LIFE_DAYS,
        inactive_strength=INACTIVE_STRENGTH,
        states_ref=refs["memory_states.jsonl"],
        views_ref=refs["memory_views.jsonl"],
        snapshot_index_ref=refs["snapshot_index.jsonl"],
        long_embeddings_ref=vector_ref,
        similarity_matrices_ref=matrix_ref,
        counts=counts,
    )
    manifest_payload = encode_json(manifest)
    manifest_ref = ResourceRef(
        store=output_root_id,
        key=f"{prefix}/manifest.json",
        version=artifact_version,
        checksum=_checksum(manifest_payload),
    )
    payload_by_ref = [
        (refs["memory_states.jsonl"], state_payload),
        (refs["memory_views.jsonl"], view_payload),
        (refs["snapshot_index.jsonl"], index_payload),
        (manifest_ref, manifest_payload),
    ]
    if vector_ref is not None:
        payload_by_ref.append((vector_ref, vector_payload))
    if matrix_ref is not None:
        payload_by_ref.append((matrix_ref, matrix_payload))
    return MemoryArtifactPlan(
        artifact_version=artifact_version,
        output_root_id=output_root_id,
        manifest=manifest,
        manifest_ref=manifest_ref,
        states=tuple(states),
        views=tuple(views),
        snapshot_index=tuple(index),
        files=tuple(sorted(payload_by_ref, key=lambda entry: entry[0].key)),
    )


class FilesystemMemoryArtifactPublisher:
    def __init__(self, registry: RootRegistry) -> None:
        self._resolver = FilesystemPathResolver(registry)

    @staticmethod
    def _verify(plan: MemoryArtifactPlan, directory: Path) -> None:
        prefix = f"bundles/{plan.artifact_version}/"
        expected: set[str] = set()
        for ref, payload in plan.files:
            name = ref.key.removeprefix(prefix)
            expected.add(name)
            try:
                actual = directory.joinpath(*name.split("/")).read_bytes()
            except OSError as exc:
                raise ArtifactIntegrityError(f"cannot verify memory artifact: {name}") from exc
            if actual != payload:
                raise ArtifactIntegrityError(f"memory artifact payload mismatch: {name}")
        try:
            actual_files = {
                path.relative_to(directory).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
            }
        except OSError as exc:
            raise ArtifactIntegrityError("cannot inventory memory artifact") from exc
        if actual_files != expected:
            raise ArtifactIntegrityError("memory artifact inventory mismatch")

    def publish(self, plan: MemoryArtifactPlan, *, execution_id: str) -> MemoryPublicationResult:
        target = self._resolver.resolve_new_path(
            plan.output_root_id, f"bundles/{plan.artifact_version}"
        )
        if target.exists():
            self._verify(plan, target)
            return MemoryPublicationResult("reused", plan.manifest_ref)
        stage = self._resolver.resolve_new_path(
            plan.output_root_id,
            publication_staging_key(plan.output_root_id, plan.artifact_version, execution_id),
        )
        prefix = f"bundles/{plan.artifact_version}/"
        try:
            stage.mkdir(parents=True, exist_ok=False)
            for ref, payload in plan.files:
                destination = stage.joinpath(*ref.key.removeprefix(prefix).split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as handle:
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
                return MemoryPublicationResult("reused", plan.manifest_ref)
            raise ArtifactPublicationError("cannot publish memory artifact") from exc
        self._verify(plan, target)
        return MemoryPublicationResult("created", plan.manifest_ref)


def _decode_jsonl_exact(payload: bytes, model_type, logical_name: str):
    try:
        records = decode_jsonl(payload, model_type, logical_name=logical_name)
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError(f"invalid {logical_name}") from exc
    if encode_jsonl(records) != payload:
        raise ArtifactIntegrityError(f"non-canonical {logical_name}")
    return records


def load_memory_artifact(
    resolver: FilesystemPathResolver, manifest_ref: ResourceRef
) -> LoadedMemoryArtifact:
    try:
        manifest = decode_canonical_json(
            resolver.read_verified_bytes(manifest_ref),
            MemoryArtifactManifest,
            logical_name="memory artifact manifest",
        )
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError("invalid memory artifact manifest") from exc
    if (
        manifest.artifact_version != manifest_ref.version
        or manifest_ref.key != f"bundles/{manifest.artifact_version}/manifest.json"
    ):
        raise ArtifactIntegrityError("memory manifest identity mismatch")
    states = _decode_jsonl_exact(
        resolver.read_verified_bytes(manifest.states_ref), MemoryStateRecord, "memory states"
    )
    views = _decode_jsonl_exact(
        resolver.read_verified_bytes(manifest.views_ref), MemoryViewRecord, "memory views"
    )
    index = _decode_jsonl_exact(
        resolver.read_verified_bytes(manifest.snapshot_index_ref),
        MemorySnapshotIndexEntry,
        "memory snapshot index",
    )
    if not (len(states) == len(views) == len(index) == manifest.counts["snapshots"]):
        raise ArtifactIntegrityError("memory snapshot payload coverage mismatch")
    for position, entry in enumerate(index):
        state = states[entry.state_line_index]
        view = views[entry.view_line_index]
        identity = (
            entry.snapshot_id,
            entry.user_id,
            entry.cutoff_identity,
            entry.history_projection_checksum,
        )
        if entry.state_line_index != position or entry.view_line_index != position:
            raise ArtifactIntegrityError("memory snapshot index is not canonical")
        if identity != (
            state.snapshot_id,
            state.user_id,
            state.cutoff_identity,
            state.history_projection_checksum,
        ) or identity != (
            view.snapshot_id,
            view.user_id,
            view.cutoff_identity,
            view.history_projection_checksum,
        ):
            raise ArtifactIntegrityError("memory snapshot identity mismatch")
        if (
            state.memory_version != entry.memory_version
            or view.view.memory_version != entry.memory_version
        ):
            raise ArtifactIntegrityError("memory version mismatch")
        if (
            _record_checksum(state) != entry.state_record_checksum
            or _record_checksum(view) != entry.view_record_checksum
        ):
            raise ArtifactIntegrityError("memory indexed record checksum mismatch")
    centroid_count = sum(len(state.tracks) for state in states)
    if centroid_count:
        if manifest.long_embeddings_ref is None:
            raise ArtifactIntegrityError("memory centroid shard is missing")
        payload = resolver.read_verified_bytes(manifest.long_embeddings_ref)
        if len(payload) != centroid_count * VECTOR_BYTES:
            raise ArtifactIntegrityError("memory centroid shard size mismatch")
    elif manifest.long_embeddings_ref is not None:
        raise ArtifactIntegrityError("empty memory cannot expose a centroid shard")
    if manifest.similarity_matrices_ref is not None:
        payload = resolver.read_verified_bytes(manifest.similarity_matrices_ref)
        if len(payload) != manifest.counts["matrix_float_count"] * 4:
            raise ArtifactIntegrityError("memory matrix shard size mismatch")
    return LoadedMemoryArtifact(manifest, states, views, index)


def resolve_memory_view(
    loaded: LoadedMemoryArtifact,
    *,
    user_id: str,
    cutoff_identity: str,
    history_projection_checksum: str,
) -> UserMemoryView:
    matches = tuple(
        entry
        for entry in loaded.snapshot_index
        if entry.user_id == user_id and entry.cutoff_identity == cutoff_identity
    )
    if len(matches) != 1:
        raise ArtifactIntegrityError("exact memory snapshot selector is unknown or ambiguous")
    entry = matches[0]
    if entry.history_projection_checksum != history_projection_checksum:
        raise ArtifactIntegrityError("memory history projection checksum mismatch")
    return loaded.views[entry.view_line_index].view


def load_similarity_matrix(
    resolver: FilesystemPathResolver, view: UserMemoryView
) -> tuple[tuple[float, ...], ...]:
    if view.similarity_matrix_ref is None:
        raise ArtifactIntegrityError("memory view has no similarity matrix")
    shape = view.metadata.get("similarity_matrix_shape")
    offset = view.metadata.get("similarity_matrix_float_offset")
    if (
        not isinstance(shape, list)
        or len(shape) != 2
        or not all(isinstance(value, int) and value > 0 for value in shape)
        or not isinstance(offset, int)
        or offset < 0
    ):
        raise ArtifactIntegrityError("memory view matrix location is invalid")
    payload = resolver.read_verified_bytes(view.similarity_matrix_ref)
    count = shape[0] * shape[1]
    start = offset * 4
    end = start + count * 4
    if end > len(payload):
        raise ArtifactIntegrityError("memory matrix location is outside its shard")
    values = struct.unpack(f"<{count}f", payload[start:end])
    if any(not math.isfinite(value) for value in values):
        raise ArtifactIntegrityError("memory matrix contains non-finite values")
    return tuple(tuple(values[row * shape[1] : (row + 1) * shape[1]]) for row in range(shape[0]))
