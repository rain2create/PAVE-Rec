"""Build the complete deterministic portable artifact graph in memory."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pave_rec.domain import ItemFeatureRef, ItemSegmentCatalog, ResourceRef, SegmentProxyRef

from .codecs import encode_json, encode_jsonl
from .components import PreprocessingComponents, project_segment_meta
from .config import Phase2PreprocessingConfig
from .identity import (
    item_feature_key,
    segment_proxy_key,
)
from .models import (
    ArtifactEntry,
    DataIdentity,
    ItemFeatureRecord,
    ItemFeatureStoreIndex,
    ReleaseManifest,
    RootBundleManifest,
    SegmentProxyRecord,
    SegmentStoreIndex,
    UserBehaviorSequence,
)
from .source import LoadedSourceDataset


def checksum_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True)
class GeneratedArtifact:
    entry: ArtifactEntry
    payload: bytes

    def __post_init__(self) -> None:
        if len(self.payload) != self.entry.size_bytes:
            raise ValueError("generated artifact byte size does not match entry")
        if checksum_bytes(self.payload) != self.entry.resource_ref.checksum:
            raise ValueError("generated artifact checksum does not match entry")


@dataclass(frozen=True)
class RootPublication:
    root_id: str
    artifacts: tuple[GeneratedArtifact, ...]
    manifest: RootBundleManifest
    manifest_ref: ResourceRef
    manifest_payload: bytes

    @property
    def files(self) -> tuple[tuple[ResourceRef, bytes], ...]:
        artifact_files = tuple(
            (entry.entry.resource_ref, entry.payload) for entry in self.artifacts
        )
        return (*artifact_files, (self.manifest_ref, self.manifest_payload))


@dataclass(frozen=True)
class ReleasePublicationPlan:
    data_version: str
    identity: DataIdentity
    roots: tuple[RootPublication, ...]
    release_manifest: ReleaseManifest
    release_ref: ResourceRef
    release_payload: bytes

    @property
    def artifact_count(self) -> int:
        return sum(len(root.artifacts) for root in self.roots)


def _resource_ref(*, store: str, key: str, version: str, payload: bytes) -> ResourceRef:
    return ResourceRef(
        store=store,
        key=key,
        version=version,
        checksum=checksum_bytes(payload),
    )


def _artifact(
    *,
    store: str,
    key: str,
    version: str,
    payload: bytes,
    artifact_kind: str,
    schema_version: str,
    record_count: int | None,
) -> GeneratedArtifact:
    ref = _resource_ref(store=store, key=key, version=version, payload=payload)
    return GeneratedArtifact(
        entry=ArtifactEntry(
            resource_ref=ref,
            artifact_kind=artifact_kind,
            schema_version=schema_version,
            size_bytes=len(payload),
            record_count=record_count,
        ),
        payload=payload,
    )


def _root_publication(
    *,
    root_id: str,
    version: str,
    identity_digest: str,
    artifacts: tuple[GeneratedArtifact, ...],
) -> RootPublication:
    ordered = tuple(
        sorted(
            artifacts,
            key=lambda value: (value.entry.resource_ref.store, value.entry.resource_ref.key),
        )
    )
    manifest = RootBundleManifest(
        schema_version="root-bundle-manifest-v1",
        data_version=version,
        root_id=root_id,
        identity_digest=identity_digest,
        artifacts=tuple(value.entry for value in ordered),
    )
    payload = encode_json(manifest)
    manifest_ref = _resource_ref(
        store=root_id,
        key=f"bundles/{version}/root_bundle_manifest.json",
        version=version,
        payload=payload,
    )
    return RootPublication(
        root_id=root_id,
        artifacts=ordered,
        manifest=manifest,
        manifest_ref=manifest_ref,
        manifest_payload=payload,
    )


def _build_feature_artifacts(
    *,
    version: str,
    root_id: str,
    records: tuple[ItemFeatureRecord, ...],
) -> tuple[tuple[GeneratedArtifact, ...], tuple[ItemFeatureRef, ...]]:
    artifacts: list[GeneratedArtifact] = []
    refs: list[ItemFeatureRef] = []
    for record in records:
        payload = encode_json(record)
        artifact = _artifact(
            store=root_id,
            key=item_feature_key(version, record.item_id),
            version=version,
            payload=payload,
            artifact_kind="item-feature",
            schema_version=record.schema_version,
            record_count=1,
        )
        artifacts.append(artifact)
        refs.append(ItemFeatureRef(item_id=record.item_id, feature_ref=artifact.entry.resource_ref))
    return tuple(artifacts), tuple(refs)


def _build_proxy_artifacts(
    *,
    version: str,
    root_id: str,
    records: tuple[SegmentProxyRecord, ...],
) -> tuple[tuple[GeneratedArtifact, ...], dict[tuple[str, str], SegmentProxyRef]]:
    artifacts: list[GeneratedArtifact] = []
    refs: dict[tuple[str, str], SegmentProxyRef] = {}
    for record in records:
        payload = encode_json(record)
        artifact = _artifact(
            store=root_id,
            key=segment_proxy_key(version, record.item_id, record.segment_id),
            version=version,
            payload=payload,
            artifact_kind="segment-proxy",
            schema_version=record.schema_version,
            record_count=1,
        )
        artifacts.append(artifact)
        identity = (record.item_id, record.segment_id)
        refs[identity] = SegmentProxyRef(
            item_id=record.item_id,
            segment_id=record.segment_id,
            feature_ref=artifact.entry.resource_ref,
            metadata={},
        )
    return tuple(artifacts), refs


def _build_catalogs(
    *,
    source: LoadedSourceDataset,
    proxy_refs: dict[tuple[str, str], SegmentProxyRef],
) -> tuple[ItemSegmentCatalog, ...]:
    catalogs: list[ItemSegmentCatalog] = []
    for index in source.segment_indexes:
        segments = tuple(
            sorted(
                (project_segment_meta(definition) for definition in index.definitions),
                key=lambda segment: (segment.start_ms, segment.end_ms, segment.segment_id),
            )
        )
        catalogs.append(
            ItemSegmentCatalog(
                item_id=index.item_id,
                segments=segments,
                segment_proxy_refs=tuple(
                    proxy_refs[(segment.item_id, segment.segment_id)] for segment in segments
                ),
            )
        )
    return tuple(catalogs)


def build_release_plan(
    *,
    version: str,
    identity: DataIdentity,
    source: LoadedSourceDataset,
    config: Phase2PreprocessingConfig,
    components: PreprocessingComponents,
) -> ReleasePublicationPlan:
    sequences: tuple[UserBehaviorSequence, ...] = components.behavior_processor.process(
        source.behavior_events
    )
    indexes = components.segment_definition_provider.build_indexes(
        source.items, source.segment_definitions
    )
    if indexes != source.segment_indexes:
        raise ValueError("segment provider output differs from validated source indexes")
    item_records = components.item_feature_extractor.extract(
        source.items, indexes, config.features.item_attributes
    )
    proxy_records = components.segment_proxy_extractor.extract(
        indexes, config.features.segment_attributes
    )
    processed_root = config.output.processed_root_id
    features_root = config.output.features_root_id
    feature_artifacts, feature_refs = _build_feature_artifacts(
        version=version, root_id=features_root, records=item_records
    )
    proxy_artifacts, proxy_refs = _build_proxy_artifacts(
        version=version, root_id=features_root, records=proxy_records
    )
    catalogs = _build_catalogs(source=source, proxy_refs=proxy_refs)
    behavior_payload = encode_jsonl(sequences)
    behavior_artifact = _artifact(
        store=processed_root,
        key=f"bundles/{version}/behavior/user_sequences.jsonl",
        version=version,
        payload=behavior_payload,
        artifact_kind="behavior-sequences",
        schema_version="user-behavior-sequence-v1",
        record_count=len(sequences),
    )
    feature_index = ItemFeatureStoreIndex(
        schema_version="item-feature-store-index-v1",
        data_version=version,
        entries=feature_refs,
    )
    feature_index_payload = encode_json(feature_index)
    feature_index_artifact = _artifact(
        store=processed_root,
        key=f"bundles/{version}/indexes/item_features.json",
        version=version,
        payload=feature_index_payload,
        artifact_kind="item-feature-store-index",
        schema_version=feature_index.schema_version,
        record_count=len(feature_index.entries),
    )
    segment_index = SegmentStoreIndex(
        schema_version="segment-store-index-v1",
        data_version=version,
        catalogs=catalogs,
    )
    segment_index_payload = encode_json(segment_index)
    segment_index_artifact = _artifact(
        store=processed_root,
        key=f"bundles/{version}/indexes/segments.json",
        version=version,
        payload=segment_index_payload,
        artifact_kind="segment-store-index",
        schema_version=segment_index.schema_version,
        record_count=len(segment_index.catalogs),
    )
    digest = version.removeprefix("p2-")
    roots = tuple(
        sorted(
            (
                _root_publication(
                    root_id=processed_root,
                    version=version,
                    identity_digest=digest,
                    artifacts=(
                        behavior_artifact,
                        feature_index_artifact,
                        segment_index_artifact,
                    ),
                ),
                _root_publication(
                    root_id=features_root,
                    version=version,
                    identity_digest=digest,
                    artifacts=(*feature_artifacts, *proxy_artifacts),
                ),
            ),
            key=lambda root: root.root_id,
        )
    )
    release = ReleaseManifest(
        schema_version="release-manifest-v1",
        data_version=version,
        identity=identity,
        root_bundle_manifest_refs=tuple(root.manifest_ref for root in roots),
        status="complete",
    )
    release_payload = encode_json(release)
    release_ref = _resource_ref(
        store=processed_root,
        key=f"releases/{version}.json",
        version=version,
        payload=release_payload,
    )
    return ReleasePublicationPlan(
        data_version=version,
        identity=identity,
        roots=roots,
        release_manifest=release,
        release_ref=release_ref,
        release_payload=release_payload,
    )
