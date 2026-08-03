from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pave_rec.domain import (
    ComponentDescriptor,
    ItemFeatureRef,
    ItemSegmentCatalog,
    ResourceRef,
    SegmentMeta,
    SegmentProxyRef,
)
from pave_rec.preprocessing.models import (
    ArtifactEntry,
    BehaviorEvent,
    DataIdentity,
    FileLocator,
    ItemFeatureRecord,
    ItemFeatureStoreIndex,
    ItemSegmentIndex,
    RangeLocator,
    ReleaseManifest,
    RootBundleManifest,
    SegmentDefinition,
    SegmentProxyRecord,
    SegmentStoreIndex,
    SequenceInteraction,
    SourceDatasetManifest,
    UserBehaviorSequence,
)

CHECKSUM = f"sha256:{'0' * 64}"


def ref(key: str, *, store: str = "source", version: str = "source-v1") -> ResourceRef:
    return ResourceRef(store=store, key=key, version=version, checksum=CHECKSUM)


def source_manifest() -> SourceDatasetManifest:
    return SourceDatasetManifest(
        schema_version="1",
        source_dataset_id="fixture",
        source_dataset_version="v1",
        behavior_events_ref=ref("behavior.jsonl"),
        items_ref=ref("items.jsonl"),
        segment_definitions_ref=ref("segments.jsonl"),
        metadata={},
    )


def artifact(key: str, *, store: str = "source") -> ArtifactEntry:
    return ArtifactEntry(
        resource_ref=ref(key, store=store),
        artifact_kind="fixture",
        schema_version="1",
        size_bytes=10,
        record_count=1,
    )


def catalog(item_id: str) -> ItemSegmentCatalog:
    segment = SegmentMeta(
        item_id=item_id,
        segment_id="segment_1",
        start_ms=0,
        end_ms=1000,
        media_ref=ref(f"media/{item_id}.bin"),
        metadata={},
    )
    proxy = SegmentProxyRef(
        item_id=item_id,
        segment_id="segment_1",
        feature_ref=ref(f"proxy/{item_id}.json", store="features"),
        metadata={},
    )
    return ItemSegmentCatalog(item_id=item_id, segments=(segment,), segment_proxy_refs=(proxy,))


def test_behavior_event_rejects_invalid_numeric_fields() -> None:
    with pytest.raises(ValidationError):
        BehaviorEvent(
            user_id="user",
            item_id="item",
            interaction_index=-1,
            occurred_at_ms=None,
            interaction_type="view",
            value=1.0,
            metadata={},
        )
    with pytest.raises(ValidationError):
        BehaviorEvent(
            user_id="user",
            item_id="item",
            interaction_index=0,
            occurred_at_ms=-1,
            interaction_type="view",
            value=float("nan"),
            metadata={},
        )


def test_user_sequence_requires_contiguous_indexes_and_timestamp_mode() -> None:
    def interaction(index: int, timestamp: int | None) -> SequenceInteraction:
        return SequenceInteraction(
            item_id="item",
            interaction_index=index,
            occurred_at_ms=timestamp,
            interaction_type="view",
            value=None,
            metadata={},
        )

    sequence = UserBehaviorSequence(
        user_id="user",
        interactions=(interaction(0, 10), interaction(1, 10)),
        metadata={},
    )
    assert tuple(entry.interaction_index for entry in sequence.interactions) == (0, 1)
    with pytest.raises(ValidationError, match="contiguous"):
        UserBehaviorSequence(user_id="user", interactions=(interaction(1, None),), metadata={})
    with pytest.raises(ValidationError, match="all timestamps"):
        UserBehaviorSequence(
            user_id="user",
            interactions=(interaction(0, None), interaction(1, 10)),
            metadata={},
        )
    with pytest.raises(ValidationError, match="monotonic"):
        UserBehaviorSequence(
            user_id="user",
            interactions=(interaction(0, 20), interaction(1, 10)),
            metadata={},
        )


def test_segment_locators_and_index_preserve_semantic_order() -> None:
    first = SegmentDefinition(
        item_id="item",
        segment_id="segment_1",
        sequence_index=0,
        locator=FileLocator(
            kind="file", media_ref=ref("media/clip.bin"), duration_ms=1500, origin=None
        ),
        metadata={},
    )
    second = SegmentDefinition(
        item_id="item",
        segment_id="segment_2",
        sequence_index=1,
        locator=RangeLocator(
            kind="range", media_ref=ref("media/source.bin"), start_ms=200, end_ms=900
        ),
        metadata={},
    )
    index = ItemSegmentIndex(item_id="item", definitions=(first, second))
    assert (first.duration_ms, second.duration_ms) == (1500, 700)
    assert index.definitions[1].segment_id == "segment_2"
    with pytest.raises(ValidationError, match="contiguous"):
        ItemSegmentIndex(item_id="item", definitions=(second,))
    with pytest.raises(ValidationError, match="match index"):
        ItemSegmentIndex(
            item_id="other",
            definitions=(first.model_copy(update={"sequence_index": 0}),),
        )


@pytest.mark.parametrize(
    ("locator", "message"),
    [
        (
            {"kind": "file", "media_ref": ref("x"), "duration_ms": 0, "origin": None},
            "positive",
        ),
        (
            {"kind": "range", "media_ref": ref("x"), "start_ms": 10, "end_ms": 10},
            "positive",
        ),
    ],
)
def test_segment_definition_rejects_invalid_locator(
    locator: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        SegmentDefinition(
            item_id="item",
            segment_id="segment",
            sequence_index=0,
            locator=locator,
            metadata={},
        )


def test_feature_records_validate_counts() -> None:
    item = ItemFeatureRecord(
        schema_version="1",
        item_id="item",
        attributes={},
        segment_count=0,
        payload_refs=(),
        metadata={},
    )
    assert item.segment_count == 0
    with pytest.raises(ValidationError, match="positive"):
        SegmentProxyRecord(
            schema_version="1",
            item_id="item",
            segment_id="segment",
            duration_ms=1,
            sequence_index=0,
            segment_count=0,
            attributes={},
            payload_refs=(),
            metadata={},
        )


def test_identity_and_manifests_require_canonical_order() -> None:
    descriptors = (
        ComponentDescriptor(role="behavior_processor", implementation="Canonical", version="1"),
    )
    with pytest.raises(ValidationError, match="canonical ResourceRef"):
        DataIdentity(
            identity_schema_version="1",
            source_manifest=source_manifest(),
            source_artifacts=(artifact("z"), artifact("a")),
            semantic_config={},
            component_descriptors=descriptors,
            output_versions={},
        )
    identity = DataIdentity(
        identity_schema_version="1",
        source_manifest=source_manifest(),
        source_artifacts=(artifact("a"), artifact("z")),
        semantic_config={},
        component_descriptors=descriptors,
        output_versions={},
    )
    with pytest.raises(ValidationError, match="canonical store/key"):
        RootBundleManifest(
            schema_version="1",
            data_version="p2-version",
            root_id="source",
            identity_digest="digest",
            artifacts=(artifact("z"), artifact("a")),
        )
    release = ReleaseManifest(
        schema_version="1",
        data_version="p2-version",
        identity=identity,
        root_bundle_manifest_refs=(ref("manifest.json"),),
        status="complete",
    )
    assert release.status == "complete"


def test_portable_manifests_reject_case_colliding_keys() -> None:
    with pytest.raises(ValidationError, match="collide"):
        RootBundleManifest(
            schema_version="1",
            data_version="p2-version",
            root_id="source",
            identity_digest="digest",
            artifacts=(artifact("A/file.json"), artifact("a/FILE.json")),
        )


def test_store_indexes_are_sorted_and_allow_empty_catalog() -> None:
    refs = (
        ItemFeatureRef(item_id="a", feature_ref=ref("a.json", store="features")),
        ItemFeatureRef(item_id="b", feature_ref=ref("b.json", store="features")),
    )
    index = ItemFeatureStoreIndex(schema_version="1", data_version="p2-v", entries=refs)
    assert len(index.entries) == 2
    with pytest.raises(ValidationError, match="sorted"):
        ItemFeatureStoreIndex(
            schema_version="1", data_version="p2-v", entries=tuple(reversed(refs))
        )
    empty = ItemSegmentCatalog(item_id="a", segments=(), segment_proxy_refs=())
    segments = SegmentStoreIndex(
        schema_version="1",
        data_version="p2-v",
        catalogs=(empty, catalog("b")),
    )
    assert segments.catalogs[0].segments == ()


def test_preprocessing_result_keeps_local_path() -> None:
    from pave_rec.preprocessing.models import PreprocessingResult

    result = PreprocessingResult(
        execution_id="execution",
        outcome="created",
        data_version="p2-v",
        release_ref=ref("releases/p2-v.json", store="processed"),
        execution_report_path=Path("runs/report.json"),
        item_count=1,
        behavior_event_count=1,
        segment_count=1,
        artifact_count=1,
    )
    assert result.execution_report_path == Path("runs/report.json")
