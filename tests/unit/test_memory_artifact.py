from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from pave_rec.domain import ResourceRef
from pave_rec.errors import ArtifactIntegrityError, ContractError
from pave_rec.phase3.input_bundle import history_prefix_checksum
from pave_rec.phase3.memory import (
    ArtifactUserMemory,
    FilesystemMemoryArtifactPublisher,
    FilesystemMemoryAuditPublisher,
    MemoryAggregateAudit,
    MemoryArtifactManifest,
    MemoryObservation,
    MemorySnapshotIndexEntry,
    MemoryStateRecord,
    MemorySupportRecord,
    MemoryTrackRecord,
    MemoryViewRecord,
    ScalarDistribution,
    build_memory_artifact_plan,
    build_memory_audit_plan,
    build_memory_snapshot,
    load_memory_artifact,
    load_memory_audit,
    load_similarity_matrix,
    resolve_memory_view,
)
from pave_rec.phase3.memory import audit as audit_module
from pave_rec.preprocessing.paths import FilesystemPathResolver, build_root_registry


def _checksum(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _ref(store: str, label: str) -> ResourceRef:
    digest = hashlib.sha256(label.encode()).hexdigest()
    return ResourceRef(
        store=store,
        key=f"bundles/{label}/manifest.json",
        version=label,
        checksum=f"sha256:{digest}",
    )


def _semantic_ref(label: str) -> ResourceRef:
    digest = hashlib.sha256(label.encode()).hexdigest()
    return ResourceRef(
        store="semantics",
        key=f"embedding-shards/{digest}.f32",
        version=f"p3vec-{digest}",
        checksum=f"sha256:{digest}",
    )


def _observation(index: int) -> MemoryObservation:
    vector = (1.0, *(0.0 for _ in range(1023)))
    return MemoryObservation(
        item_id=f"item-{index}",
        prototype_id=f"prototype-{index}",
        semantic_text=f"semantic item {index}",
        embedding_ref=_semantic_ref(f"semantic-{index}"),
        embedding_row_index=index,
        interaction_index=index,
        occurred_at_ms=index + 100,
        vector=vector,
    )


def _plan(*, history_checksum: str | None = None):
    snapshot = build_memory_snapshot(
        user_id="user-1",
        cutoff_identity="validation-cutoff",
        history_projection_checksum=history_checksum or _checksum("history"),
        observations=(_observation(0), _observation(1)),
    )
    return build_memory_artifact_plan(
        output_root_id="memory",
        source_release_ref=_ref("processed", "p2-source"),
        derived_artifact_ref=_ref("derived", "p3-derived"),
        semantic_artifact_ref=_ref("semantics", "p3-semantic"),
        snapshots=(snapshot,),
    )


def test_memory_artifact_publish_reload_resolve_and_reuse(tmp_path, monkeypatch) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    registry = build_root_registry({"memory": (str(root), "write_new")}, project_root=tmp_path)
    plan = _plan()
    publisher = FilesystemMemoryArtifactPublisher(registry)
    first = publisher.publish(plan, execution_id="first")
    second = publisher.publish(plan, execution_id="second")
    assert first.outcome == "created"
    assert second.outcome == "reused"

    resolver = FilesystemPathResolver(registry)
    loaded = load_memory_artifact(resolver, first.manifest_ref)
    view = resolve_memory_view(
        loaded,
        user_id="user-1",
        cutoff_identity="validation-cutoff",
        history_projection_checksum=_checksum("history"),
    )
    assert view.memory_version == loaded.snapshot_index[0].memory_version
    assert view.metadata["similarity_matrix_float_offset"] == 0
    matrix = load_similarity_matrix(resolver, view)
    assert len(matrix) == 1
    assert matrix[0] == pytest.approx((1.0, 1.0))

    audit_root = tmp_path / "memory-audits"
    audit_root.mkdir()
    audit_registry = build_root_registry(
        {"memory_audits": (str(audit_root), "write_new")},
        project_root=tmp_path,
    )
    audit_plan = build_memory_audit_plan(
        output_root_id="memory_audits",
        memory_artifact_ref=first.manifest_ref,
        loaded=loaded,
    )
    audit_publisher = FilesystemMemoryAuditPublisher(audit_registry)
    published_audit = audit_publisher.publish(audit_plan, execution_id="first")
    assert audit_publisher.publish(audit_plan, execution_id="second").outcome == "reused"
    audit = load_memory_audit(FilesystemPathResolver(audit_registry), published_audit.audit_ref)
    assert audit.counts["snapshots"] == 1
    assert audit.counts["semantic_observations"] == 2
    assert audit.rates["snapshot_semantic_coverage"] == 1.0
    assert audit.distributions["cosine_similarity"].count > 0

    config_path = tmp_path / "audit.yaml"
    config_path.write_text("fixture\n", encoding="utf-8")
    loaded_config = SimpleNamespace(
        config=SimpleNamespace(
            memory_artifact_ref=first.manifest_ref,
            output_root_id="memory_audits",
        ),
        config_path=config_path,
        project_root=tmp_path,
        root_registry=audit_registry,
    )
    monkeypatch.setattr(
        audit_module,
        "load_phase3_memory_audit_config",
        lambda _: loaded_config,
    )
    monkeypatch.setattr(audit_module, "load_memory_artifact", lambda resolver, ref: loaded)
    lifecycle = audit_module.audit_memory_from_config(config_path)
    assert lifecycle.outcome == "reused"
    assert lifecycle.snapshots == 1
    assert lifecycle.semantic_observations == 2


def test_memory_artifact_is_byte_deterministic_and_fails_wrong_history(tmp_path) -> None:
    left = _plan()
    right = _plan()
    assert left.artifact_version == right.artifact_version
    assert left.files == right.files

    root = tmp_path / "memory"
    root.mkdir()
    registry = build_root_registry({"memory": (str(root), "write_new")}, project_root=tmp_path)
    publication = FilesystemMemoryArtifactPublisher(registry).publish(left, execution_id="build")
    loaded = load_memory_artifact(FilesystemPathResolver(registry), publication.manifest_ref)
    with pytest.raises(ArtifactIntegrityError, match="history projection"):
        resolve_memory_view(
            loaded,
            user_id="user-1",
            cutoff_identity="validation-cutoff",
            history_projection_checksum=_checksum("wrong"),
        )


def test_memory_artifact_corruption_is_detected(tmp_path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    registry = build_root_registry({"memory": (str(root), "write_new")}, project_root=tmp_path)
    plan = _plan()
    FilesystemMemoryArtifactPublisher(registry).publish(plan, execution_id="build")
    matrix_ref = plan.manifest.similarity_matrices_ref
    assert matrix_ref is not None
    matrix_path = root.joinpath(*matrix_ref.key.split("/"))
    matrix_path.write_bytes(b"corrupt")
    with pytest.raises(Exception, match="checksum"):
        load_memory_artifact(FilesystemPathResolver(registry), plan.manifest_ref)


def test_artifact_user_memory_is_exact_bound_and_read_only(tmp_path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    registry = build_root_registry({"memory": (str(root), "write_new")}, project_root=tmp_path)
    history = ("item-0", "item-1")
    checksum = history_prefix_checksum("user-1", history)
    plan = _plan(history_checksum=checksum)
    publication = FilesystemMemoryArtifactPublisher(registry).publish(plan, execution_id="adapter")
    loaded = load_memory_artifact(FilesystemPathResolver(registry), publication.manifest_ref)
    adapter = ArtifactUserMemory(
        loaded,
        bound_user_id="user-1",
        bound_cutoff_identity="validation-cutoff",
        bound_history_projection_checksum=checksum,
    )
    first = adapter.build_or_update("user-1", history)
    second = adapter.build_or_update("user-1", history)
    assert first is second
    with pytest.raises(ContractError, match="history"):
        adapter.build_or_update("user-1", ("item-0",))


def _reject(model, value, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(value)


def test_memory_records_reject_invalid_tracks_snapshots_and_indexes() -> None:
    plan = _plan()
    state = plan.states[0]
    track = state.tracks[0]
    support = track.supports[0]
    support_data = support.model_dump(mode="python")
    for field in ("item_id", "prototype_id"):
        _reject(
            MemorySupportRecord,
            {**support_data, field: ""},
            "must be a non-empty string",
        )
    _reject(
        MemorySupportRecord,
        {**support_data, "source_interaction_index": -1},
        "must be non-negative",
    )

    track_data = track.model_dump(mode="python")
    for field in ("atom_id", "medoid_prototype_id", "medoid_text"):
        _reject(MemoryTrackRecord, {**track_data, field: ""}, "non-empty string")
    _reject(MemoryTrackRecord, {**track_data, "centroid_row_index": -1}, "non-negative")
    _reject(MemoryTrackRecord, {**track_data, "strength": 1.1}, "must be in")
    _reject(MemoryTrackRecord, {**track_data, "supports": ()}, "require support")
    if len(track.supports) > 1:
        _reject(
            MemoryTrackRecord,
            {**track_data, "supports": tuple(reversed(track.supports))},
            "must be chronological",
        )
    _reject(
        MemoryTrackRecord,
        {**track_data, "kind": "pending", "state": "stable"},
        "pending tracks must be emerging",
    )
    _reject(
        MemoryTrackRecord,
        {**track_data, "kind": "long", "state": "emerging"},
        "long tracks cannot be emerging",
    )
    _reject(
        MemoryTrackRecord,
        {**track_data, "centroid_ref": track.centroid_ref.model_copy(update={"checksum": "bad"})},
        "must be sha256",
    )

    state_data = state.model_dump(mode="python")
    _reject(MemoryStateRecord, {**state_data, "snapshot_id": "bad"}, "p3snapshot")
    _reject(MemoryStateRecord, {**state_data, "memory_version": "bad"}, "p3memory")
    _reject(MemoryStateRecord, {**state_data, "user_id": ""}, "non-empty string")
    _reject(MemoryStateRecord, {**state_data, "history_projection_checksum": "bad"}, "sha256")
    _reject(MemoryStateRecord, {**state_data, "updated_at_ms": -1}, "non-negative")
    _reject(MemoryStateRecord, {**state_data, "promotion_count": -1}, "non-negative")
    _reject(
        MemoryStateRecord,
        {**state_data, "tracks": (track, track)},
        "must not contain duplicates",
    )

    view = plan.views[0]
    view_data = view.model_dump(mode="python")
    _reject(MemoryViewRecord, {**view_data, "snapshot_id": "bad"}, "p3snapshot")
    _reject(MemoryViewRecord, {**view_data, "cutoff_identity": ""}, "non-empty string")
    _reject(MemoryViewRecord, {**view_data, "history_projection_checksum": "bad"}, "sha256")

    index = plan.snapshot_index[0]
    index_data = index.model_dump(mode="python")
    _reject(MemorySnapshotIndexEntry, {**index_data, "snapshot_id": "bad"}, "p3snapshot")
    _reject(MemorySnapshotIndexEntry, {**index_data, "memory_version": "bad"}, "p3memory")
    _reject(MemorySnapshotIndexEntry, {**index_data, "user_id": ""}, "non-empty string")
    _reject(MemorySnapshotIndexEntry, {**index_data, "state_record_checksum": "bad"}, "sha256")
    _reject(MemorySnapshotIndexEntry, {**index_data, "view_line_index": -1}, "non-negative")


def test_memory_manifest_and_audit_models_reject_inconsistent_inventories() -> None:
    plan = _plan()
    manifest = plan.manifest.model_dump(mode="python")
    _reject(MemoryArtifactManifest, {**manifest, "artifact_version": "bad"}, "p3memoryartifact")
    _reject(
        MemoryArtifactManifest,
        {
            **manifest,
            "states_ref": plan.manifest.states_ref.model_copy(update={"version": "other"}),
        },
        "payload ref version mismatch",
    )
    _reject(MemoryArtifactManifest, {**manifest, "counts": {"snapshots": 1}}, "inventory")
    without_embeddings = dict(manifest)
    without_embeddings["long_embeddings_ref"] = None
    _reject(MemoryArtifactManifest, without_embeddings, "embedding ref/count mismatch")
    without_matrix = dict(manifest)
    without_matrix["similarity_matrices_ref"] = None
    _reject(MemoryArtifactManifest, without_matrix, "matrix ref/count mismatch")

    _reject(
        ScalarDistribution,
        {
            "count": -1,
            "minimum": None,
            "mean": None,
            "p50": None,
            "p90": None,
            "p99": None,
            "maximum": None,
        },
        "non-negative",
    )
    _reject(
        ScalarDistribution,
        {
            "count": 0,
            "minimum": 0.0,
            "mean": None,
            "p50": None,
            "p90": None,
            "p99": None,
            "maximum": None,
        },
        "presence mismatch",
    )
    _reject(
        ScalarDistribution,
        {
            "count": 1,
            "minimum": 0.0,
            "mean": None,
            "p50": 0.0,
            "p90": 0.0,
            "p99": 0.0,
            "maximum": 0.0,
        },
        "requires every summary",
    )
    audit_plan = build_memory_audit_plan(
        output_root_id="audits",
        memory_artifact_ref=plan.manifest_ref,
        loaded=SimpleNamespace(
            manifest=plan.manifest,
            states=plan.states,
            views=plan.views,
        ),
    )
    audit = audit_plan.audit.model_dump(mode="python")
    _reject(MemoryAggregateAudit, {**audit, "audit_version": "bad"}, "p3memoryaudit")
    _reject(MemoryAggregateAudit, {**audit, "counts": {}}, "count inventory")
    _reject(MemoryAggregateAudit, {**audit, "rates": {}}, "rate inventory")
    invalid_rates = dict(audit["rates"])
    invalid_rates["snapshot_semantic_coverage"] = float("nan")
    _reject(MemoryAggregateAudit, {**audit, "rates": invalid_rates}, "finite")
    _reject(MemoryAggregateAudit, {**audit, "distributions": {}}, "distribution inventory")
