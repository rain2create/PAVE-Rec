from __future__ import annotations

import hashlib
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import (
    ArtifactIntegrityError,
    ComponentExecutionError,
    ConfigurationError,
)
from pave_rec.phase3.semantics import (
    BgeM3EmbeddingProvider,
    BgeM3SnapshotManifest,
    EmbeddingIndexEntry,
    EmbeddingResult,
    FilesystemItemSemanticPublisher,
    FixtureEmbeddingProvider,
    ItemSemanticArtifactManifest,
    ItemSemanticPrototype,
    ModelSnapshotFile,
    build_item_semantic_artifact_plan,
    build_semantic_text,
    fetch_bge_m3_snapshot,
    load_item_semantics,
    load_prototype_embedding,
    normalize_embedding,
    verify_model_snapshot,
)
from pave_rec.phase3.semantics.fetch import BGE_M3_REVISION, BGE_M3_RUNTIME_INVENTORY
from pave_rec.preprocessing.models import ItemFeatureRecord
from pave_rec.preprocessing.paths import FilesystemPathResolver, build_root_registry


def _record(item_id: str, attributes: dict) -> ItemFeatureRecord:
    return ItemFeatureRecord(
        schema_version="item-feature-v1",
        item_id=item_id,
        attributes=attributes,
        segment_count=0,
        payload_refs=(),
        metadata={},
    )


def _unit_vector(index: int) -> tuple[float, ...]:
    return tuple(1.0 if position == index else 0.0 for position in range(1024))


def test_semantic_text_uses_only_actual_fields_in_canonical_order() -> None:
    version = f"p2-{'a' * 64}"
    spec = build_semantic_text(
        _record(
            "item-a",
            {
                "title_cn": "为什么这是合法的吗",
                "tags": ["法治", "社会"],
                "category_paths_cn": ["新闻 > 社会"],
                "category_paths_en": ["news > society"],
            },
        ),
        source_data_version=version,
    )
    assert spec is not None
    assert spec.semantic_text == ("标题：为什么这是合法的吗\n标签：法治；社会\n分类：新闻 > 社会")
    assert spec.included_fields == ("title_cn", "tags", "category_paths_cn")
    assert "description" not in spec.semantic_text and "news" not in spec.semantic_text

    without_title = build_semantic_text(
        _record(
            "item-b",
            {"tags": ["混合language"], "category_paths_cn": ["知识"]},
        ),
        source_data_version=version,
    )
    assert without_title is not None
    assert without_title.semantic_text == "标签：混合language\n分类：知识"
    assert without_title.included_fields == ("tags", "category_paths_cn")
    assert (
        build_semantic_text(
            _record("item-c", {}),
            source_data_version=version,
        )
        is None
    )


def test_semantic_artifact_deduplicates_vectors_not_item_identity_and_loads_exactly(
    tmp_path: Path,
) -> None:
    version = f"p2-{'a' * 64}"
    records = (
        _record("item-a", {"tags": ["相同"], "category_paths_cn": ["分类"]}),
        _record("item-b", {"tags": ["相同"], "category_paths_cn": ["分类"]}),
        _record("item-c", {}),
    )
    specs = tuple(
        spec
        for record in records
        if (spec := build_semantic_text(record, source_data_version=version)) is not None
    )
    assert specs[0].semantic_text == specs[1].semantic_text
    assert specs[0].prototype_id != specs[1].prototype_id
    provider = FixtureEmbeddingProvider({specs[0].semantic_text: _unit_vector(7)})
    result = provider.encode((specs[0].semantic_text,))[0]
    source_ref = ResourceRef(
        store="processed",
        key=f"releases/{version}.json",
        version=version,
        checksum=f"sha256:{'b' * 64}",
    )
    plan = build_item_semantic_artifact_plan(
        output_root_id="semantics",
        source_data_version=version,
        source_release_ref=source_ref,
        source_item_count=3,
        specs=specs,
        embeddings_by_text_checksum={specs[0].semantic_text_sha256: result},
        model_snapshot_checksum=provider.snapshot_checksum,
    )
    assert plan.manifest.counts["semantic_items"] == 2
    assert plan.manifest.counts["missing_semantics"] == 1
    assert plan.manifest.counts["unique_semantic_texts"] == 1
    assert plan.prototypes[0].embedding_ref == plan.prototypes[1].embedding_ref
    assert plan.prototypes[0].embedding_row_index == plan.prototypes[1].embedding_row_index

    root = tmp_path / "semantics"
    root.mkdir()
    write_registry = build_root_registry(
        {"semantics": (str(root), "write_new")}, project_root=tmp_path
    )
    publisher = FilesystemItemSemanticPublisher(write_registry)
    assert publisher.publish(plan, execution_id="first").outcome == "created"
    assert publisher.publish(plan, execution_id="second").outcome == "reused"

    read_registry = build_root_registry(
        {"semantics": (str(root), "read_only")}, project_root=tmp_path
    )
    resolver = FilesystemPathResolver(read_registry)
    loaded = load_item_semantics(resolver, plan.manifest_ref)
    assert loaded.manifest == plan.manifest
    assert loaded.prototypes == plan.prototypes
    vector = load_prototype_embedding(resolver, loaded.prototypes[0])
    assert vector[7] == pytest.approx(1.0)
    assert sum(value != 0.0 for value in vector) == 1

    shard_ref = plan.manifest.embedding_shard_refs[0]
    shard_path = root.joinpath(*shard_ref.key.split("/"))
    shard_path.write_bytes(b"corrupt")
    with pytest.raises(ArtifactIntegrityError):
        load_prototype_embedding(resolver, loaded.prototypes[0])


def test_pinned_bge_provider_verifies_snapshot_and_normalizes_fake_dense_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    payload = b"pinned-model"
    (snapshot / "config.json").write_bytes(payload)
    manifest = BgeM3SnapshotManifest(
        schema_version="bge-m3-model-snapshot-v1",
        model_id="BAAI/bge-m3",
        revision=BGE_M3_REVISION,
        files=(
            ModelSnapshotFile(
                relative_path="config.json",
                size_bytes=len(payload),
                checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            ),
        ),
    )

    class FakeBgeModel:
        def __init__(self, model_root: str, *, use_fp16: bool, device: str) -> None:
            assert Path(model_root) == snapshot
            assert use_fp16 is False
            assert device == "cpu"
            self.tokenizer = lambda text, **kwargs: {
                "input_ids": list(range(1025 if text == "long" else 3))
            }

        def encode(self, texts, **kwargs):
            assert kwargs["return_dense"] is True
            return {"dense_vecs": [_unit_vector(9) for _ in texts]}

    monkeypatch.setattr("importlib.metadata.version", lambda _: "1.4.0")
    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        SimpleNamespace(BGEM3FlagModel=FakeBgeModel),
    )
    provider = BgeM3EmbeddingProvider(
        snapshot_root=snapshot,
        snapshot_manifest=manifest,
        snapshot_checksum=f"sha256:{'d' * 64}",
        device="cpu",
        batch_size=2,
    )
    assert provider.encode(()) == ()
    encoded = provider.encode(("short", "long"))
    assert encoded[0].vector[9] == 1.0
    assert encoded[0].token_count == 3
    assert encoded[1].was_truncated is True


def test_model_fetch_reuses_complete_local_pinned_inventory(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    manifests = tmp_path / "manifests"
    snapshot = cache / "models--BAAI--bge-m3" / "snapshots" / BGE_M3_REVISION
    manifests.mkdir()
    for relative_path in BGE_M3_RUNTIME_INVENTORY:
        destination = snapshot.joinpath(*relative_path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(relative_path.encode("utf-8"))
    first = fetch_bge_m3_snapshot(cache_root=cache, manifest_root=manifests)
    second = fetch_bge_m3_snapshot(cache_root=cache, manifest_root=manifests)
    assert first.outcome == "created"
    assert second.outcome == "reused"
    manifest_payload = (manifests / first.manifest_filename).read_bytes()
    manifest = BgeM3SnapshotManifest.model_validate_json(manifest_payload)
    assert manifest_payload == canonical_json_bytes(manifest, pretty=True)
    assert first.file_count == len(BGE_M3_RUNTIME_INVENTORY)


def _reject(model, value, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(value)


def _semantic_plan():
    version = f"p2-{'a' * 64}"
    spec = build_semantic_text(
        _record("item-a", {"title_cn": "标题", "tags": ["标签"]}),
        source_data_version=version,
    )
    assert spec is not None
    provider = FixtureEmbeddingProvider({spec.semantic_text: _unit_vector(0)})
    encoded = provider.encode((spec.semantic_text,))[0]
    return build_item_semantic_artifact_plan(
        output_root_id="semantics",
        source_data_version=version,
        source_release_ref=ResourceRef(
            store="processed",
            key=f"releases/{version}.json",
            version=version,
            checksum=f"sha256:{'b' * 64}",
        ),
        source_item_count=1,
        specs=(spec,),
        embeddings_by_text_checksum={spec.semantic_text_sha256: encoded},
        model_snapshot_checksum=provider.snapshot_checksum,
    )


def test_semantic_records_reject_invalid_snapshot_prototype_and_index() -> None:
    file = ModelSnapshotFile(
        relative_path="config.json",
        size_bytes=1,
        checksum=f"sha256:{'a' * 64}",
    )
    _reject(
        ModelSnapshotFile,
        {"relative_path": "../config.json", "size_bytes": 1, "checksum": file.checksum},
        "dot path segment",
    )
    _reject(
        ModelSnapshotFile,
        {"relative_path": "config.json", "size_bytes": 0, "checksum": file.checksum},
        "must not be empty",
    )
    _reject(
        ModelSnapshotFile,
        {"relative_path": "config.json", "size_bytes": 1, "checksum": "bad"},
        "must be sha256",
    )
    snapshot = {
        "schema_version": "bge-m3-model-snapshot-v1",
        "model_id": "BAAI/bge-m3",
        "revision": BGE_M3_REVISION,
        "files": (file,),
    }
    _reject(BgeM3SnapshotManifest, {**snapshot, "files": ()}, "must not be empty")
    _reject(BgeM3SnapshotManifest, {**snapshot, "files": (file, file)}, "duplicates")
    other = file.model_copy(update={"relative_path": "a.json"})
    _reject(BgeM3SnapshotManifest, {**snapshot, "files": (file, other)}, "canonical path order")

    plan = _semantic_plan()
    prototype = plan.prototypes[0]
    prototype_data = prototype.model_dump(mode="python")
    _reject(ItemSemanticPrototype, {**prototype_data, "prototype_id": "bad"}, "p3proto")
    _reject(ItemSemanticPrototype, {**prototype_data, "item_id": ""}, "non-empty string")
    _reject(
        ItemSemanticPrototype,
        {**prototype_data, "semantic_text_sha256": "bad"},
        "must be sha256",
    )
    _reject(
        ItemSemanticPrototype,
        {**prototype_data, "embedding_row_index": -1},
        "non-negative",
    )
    _reject(ItemSemanticPrototype, {**prototype_data, "included_fields": ()}, "canonical subset")
    _reject(
        ItemSemanticPrototype,
        {**prototype_data, "included_fields": ("tags", "title_cn")},
        "canonical subset",
    )
    _reject(
        ItemSemanticPrototype,
        {
            **prototype_data,
            "embedding_ref": prototype.embedding_ref.model_copy(update={"version": "bad"}),
        },
        "requires a p3vec version",
    )

    index = plan.embedding_index[0]
    index_data = index.model_dump(mode="python")
    _reject(EmbeddingIndexEntry, {**index_data, "prototype_id": "bad"}, "p3proto")
    _reject(EmbeddingIndexEntry, {**index_data, "item_id": ""}, "non-empty string")
    _reject(EmbeddingIndexEntry, {**index_data, "semantic_text_sha256": "bad"}, "sha256")
    _reject(EmbeddingIndexEntry, {**index_data, "token_count": -1}, "non-negative")
    _reject(
        EmbeddingIndexEntry,
        {**index_data, "embedding_ref": index.embedding_ref.model_copy(update={"version": "bad"})},
        "requires a p3vec version",
    )


def test_semantic_manifest_rejects_cross_artifact_identity_and_count_drift() -> None:
    plan = _semantic_plan()
    manifest = plan.manifest.model_dump(mode="python")
    _reject(ItemSemanticArtifactManifest, {**manifest, "semantic_version": "bad"}, "p3semantic")
    _reject(
        ItemSemanticArtifactManifest,
        {**manifest, "source_data_version": "bad"},
        "data version",
    )
    _reject(
        ItemSemanticArtifactManifest,
        {**manifest, "model_snapshot_checksum": "bad"},
        "sha256",
    )
    _reject(
        ItemSemanticArtifactManifest,
        {
            **manifest,
            "source_release_ref": plan.manifest.source_release_ref.model_copy(
                update={"version": "other"}
            ),
        },
        "source release ref/data version mismatch",
    )
    _reject(
        ItemSemanticArtifactManifest,
        {
            **manifest,
            "semantic_items_ref": plan.manifest.semantic_items_ref.model_copy(
                update={"version": "other"}
            ),
        },
        "singleton ref identity mismatch",
    )
    _reject(
        ItemSemanticArtifactManifest,
        {**manifest, "embedding_shard_refs": ()},
        "requires embedding shards",
    )
    _reject(ItemSemanticArtifactManifest, {**manifest, "counts": {}}, "count inventory")
    counts = dict(manifest["counts"])
    counts["source_items"] = 2
    _reject(ItemSemanticArtifactManifest, {**manifest, "counts": counts}, "must partition")
    counts = dict(manifest["counts"])
    counts["embedding_shards"] = 2
    _reject(ItemSemanticArtifactManifest, {**manifest, "counts": counts}, "shard count mismatch")
    counts = dict(manifest["counts"])
    counts["unique_semantic_texts"] = 2
    _reject(ItemSemanticArtifactManifest, {**manifest, "counts": counts}, "exceeds semantic item")
    counts = dict(manifest["counts"])
    counts["truncated_texts"] = 2
    _reject(ItemSemanticArtifactManifest, {**manifest, "counts": counts}, "exceeds unique")
    shard = plan.manifest.embedding_shard_refs[0]
    duplicate_counts = dict(manifest["counts"])
    duplicate_counts["embedding_shards"] = 2
    _reject(
        ItemSemanticArtifactManifest,
        {
            **manifest,
            "embedding_shard_refs": (shard, shard),
            "counts": duplicate_counts,
        },
        "must be unique",
    )
    _reject(
        ItemSemanticArtifactManifest,
        {
            **manifest,
            "embedding_shard_refs": (shard.model_copy(update={"store": "other"}),),
        },
        "shard ref identity mismatch",
    )


def test_embedding_provider_rejects_invalid_vectors_and_unknown_fixture_text() -> None:
    with pytest.raises(ValueError, match="dimension"):
        EmbeddingResult(vector=(1.0,), token_count=1, was_truncated=False)
    with pytest.raises(ValueError, match="token count"):
        EmbeddingResult(vector=_unit_vector(0), token_count=-1, was_truncated=False)
    nonfinite = list(_unit_vector(0))
    nonfinite[0] = float("nan")
    with pytest.raises(ValueError, match="must be finite"):
        EmbeddingResult(vector=tuple(nonfinite), token_count=1, was_truncated=False)
    with pytest.raises(ValueError, match="L2-normalized"):
        EmbeddingResult(vector=tuple(0.5 for _ in range(1024)), token_count=1, was_truncated=False)
    with pytest.raises(ComponentExecutionError, match="invalid dense output"):
        normalize_embedding((1.0,), token_count=1, was_truncated=False)
    with pytest.raises(ComponentExecutionError, match="zero/non-finite"):
        normalize_embedding((0.0,) * 1024, token_count=1, was_truncated=False)
    with pytest.raises(ComponentExecutionError, match="unknown semantic text"):
        FixtureEmbeddingProvider({}).encode(("unknown",))


def test_snapshot_verification_and_provider_initialization_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"model"
    file = ModelSnapshotFile(
        relative_path="config.json",
        size_bytes=len(payload),
        checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
    )
    manifest = BgeM3SnapshotManifest(
        schema_version="bge-m3-model-snapshot-v1",
        model_id="BAAI/bge-m3",
        revision=BGE_M3_REVISION,
        files=(file,),
    )
    with pytest.raises(ArtifactIntegrityError, match="cannot resolve"):
        verify_model_snapshot(tmp_path / "missing", manifest)

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "extra.json").write_bytes(payload)
    with pytest.raises(ArtifactIntegrityError, match="inventory mismatch"):
        verify_model_snapshot(snapshot, manifest)
    (snapshot / "extra.json").unlink()
    (snapshot / "config.json").write_bytes(b"x")
    with pytest.raises(ArtifactIntegrityError, match="size mismatch"):
        verify_model_snapshot(snapshot, manifest)
    (snapshot / "config.json").write_bytes(b"other")
    same_size_manifest = manifest.model_copy(
        update={"files": (file.model_copy(update={"size_bytes": len(b"other")}),)}
    )
    with pytest.raises(ArtifactIntegrityError, match="checksum mismatch"):
        verify_model_snapshot(snapshot, same_size_manifest)
    (snapshot / "config.json").write_bytes(payload)

    with pytest.raises(ConfigurationError, match="batch size"):
        BgeM3EmbeddingProvider(
            snapshot_root=snapshot,
            snapshot_manifest=manifest,
            snapshot_checksum=file.checksum,
            device="cpu",
            batch_size=0,
        )
    monkeypatch.setattr(
        "importlib.metadata.version",
        lambda _: (_ for _ in ()).throw(PackageNotFoundError()),
    )
    with pytest.raises(ConfigurationError, match="is required"):
        BgeM3EmbeddingProvider(
            snapshot_root=snapshot,
            snapshot_manifest=manifest,
            snapshot_checksum=file.checksum,
            device="cpu",
            batch_size=1,
        )
    monkeypatch.setattr("importlib.metadata.version", lambda _: "1.3.0")
    with pytest.raises(ConfigurationError, match="exactly 1.4.0"):
        BgeM3EmbeddingProvider(
            snapshot_root=snapshot,
            snapshot_manifest=manifest,
            snapshot_checksum=file.checksum,
            device="cpu",
            batch_size=1,
        )


def test_bge_provider_rejects_encoding_failure_and_output_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    payload = b"model"
    (snapshot / "config.json").write_bytes(payload)
    manifest = BgeM3SnapshotManifest(
        schema_version="bge-m3-model-snapshot-v1",
        model_id="BAAI/bge-m3",
        revision=BGE_M3_REVISION,
        files=(
            ModelSnapshotFile(
                relative_path="config.json",
                size_bytes=len(payload),
                checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            ),
        ),
    )

    class FailingModel:
        def __init__(self, *args, **kwargs) -> None:
            self.tokenizer = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bad"))

        def encode(self, *args, **kwargs):
            return {"dense_vecs": ()}

    monkeypatch.setattr("importlib.metadata.version", lambda _: "1.4.0")
    monkeypatch.setitem(sys.modules, "FlagEmbedding", SimpleNamespace(BGEM3FlagModel=FailingModel))
    provider = BgeM3EmbeddingProvider(
        snapshot_root=snapshot,
        snapshot_manifest=manifest,
        snapshot_checksum=f"sha256:{'d' * 64}",
        device="cpu",
        batch_size=1,
    )
    with pytest.raises(ComponentExecutionError, match="encoding failed"):
        provider.encode(("text",))

    provider._model = SimpleNamespace(
        tokenizer=lambda *args, **kwargs: {"input_ids": (1,)},
        encode=lambda *args, **kwargs: {"dense_vecs": ()},
    )
    with pytest.raises(ComponentExecutionError, match="coverage mismatch"):
        provider.encode(("text",))
