"""Strict one-pass ingestion of a complete Phase 2 source dataset."""

from __future__ import annotations

from dataclasses import dataclass

from pave_rec.domain import ResourceRef
from pave_rec.errors import DatasetValidationError, ResourceResolutionError

from .codecs import decode_json, decode_jsonl, encode_jsonl
from .config import LimitConfig, LoadedPreprocessingConfig
from .models import (
    ArtifactEntry,
    BehaviorEvent,
    FileLocator,
    ItemSegmentIndex,
    SegmentDefinition,
    SourceDatasetManifest,
    SourceItem,
)
from .paths import (
    FilesystemPathResolver,
    RootRegistry,
    require_sha256,
    validate_resource_ref_collisions,
)


def resource_identity(ref: ResourceRef) -> tuple[str, str, str, str]:
    return (ref.store, ref.key, ref.version, ref.checksum or "")


def _validate_source_ref_collisions(refs: tuple[ResourceRef, ...]) -> None:
    try:
        validate_resource_ref_collisions(refs)
    except ValueError as exc:
        raise ResourceResolutionError(f"source resource key collision: {exc}") from exc


@dataclass(frozen=True)
class LoadedSourceDataset:
    manifest: SourceDatasetManifest
    items: tuple[SourceItem, ...]
    behavior_events: tuple[BehaviorEvent, ...]
    segment_definitions: tuple[SegmentDefinition, ...]
    segment_indexes: tuple[ItemSegmentIndex, ...]
    source_artifacts: tuple[ArtifactEntry, ...]


def _require_read_only(registry: RootRegistry, ref: ResourceRef) -> None:
    root = registry.require(ref.store)
    if root.access != "read_only":
        raise ResourceResolutionError(
            f"source resource must use a read_only root: {ref.store}/{ref.key}"
        )
    try:
        require_sha256(ref.checksum)
    except ValueError as exc:
        raise ResourceResolutionError(f"invalid source checksum: {ref.store}/{ref.key}") from exc


def _validate_items(items: tuple[SourceItem, ...]) -> tuple[SourceItem, ...]:
    if not items:
        raise DatasetValidationError("source item catalog must not be empty")
    item_ids = tuple(entry.item_id for entry in items)
    if len(item_ids) != len(set(item_ids)):
        raise DatasetValidationError("source item catalog contains duplicate item IDs")
    if item_ids != tuple(sorted(item_ids)):
        raise DatasetValidationError("source items must be sorted by item_id")
    return items


def _validate_behaviors(
    events: tuple[BehaviorEvent, ...], item_ids: frozenset[str]
) -> tuple[BehaviorEvent, ...]:
    if not events:
        raise DatasetValidationError("source behavior events must not be empty")
    identities = tuple((entry.user_id, entry.interaction_index) for entry in events)
    if len(identities) != len(set(identities)):
        raise DatasetValidationError("behavior events contain duplicate user/index identities")
    if identities != tuple(sorted(identities)):
        raise DatasetValidationError("behavior events must use canonical user/index order")
    if any(entry.item_id not in item_ids for entry in events):
        raise DatasetValidationError("behavior event references an unknown item")
    by_user: dict[str, list[BehaviorEvent]] = {}
    for event in events:
        by_user.setdefault(event.user_id, []).append(event)
    for user_id, user_events in by_user.items():
        indexes = tuple(entry.interaction_index for entry in user_events)
        if indexes != tuple(range(len(indexes))):
            raise DatasetValidationError(
                f"behavior indexes must be contiguous from zero for user {user_id}"
            )
        timestamps = tuple(entry.occurred_at_ms for entry in user_events)
        has_null = any(value is None for value in timestamps)
        has_value = any(value is not None for value in timestamps)
        if has_null and has_value:
            raise DatasetValidationError(
                f"timestamps must be all present or all null for user {user_id}"
            )
        provided = tuple(value for value in timestamps if value is not None)
        if provided != tuple(sorted(provided)):
            raise DatasetValidationError(f"timestamps are not monotonic for user {user_id}")
    return events


def _build_segment_indexes(
    items: tuple[SourceItem, ...], definitions: tuple[SegmentDefinition, ...]
) -> tuple[ItemSegmentIndex, ...]:
    order = tuple((entry.item_id, entry.sequence_index) for entry in definitions)
    if order != tuple(sorted(order)):
        raise DatasetValidationError("segment definitions must use canonical item/sequence order")
    item_ids = {entry.item_id for entry in items}
    if any(entry.item_id not in item_ids for entry in definitions):
        raise DatasetValidationError("segment definition references an unknown item")
    by_item: dict[str, list[SegmentDefinition]] = {item_id: [] for item_id in item_ids}
    for definition in definitions:
        by_item[definition.item_id].append(definition)
    try:
        return tuple(
            ItemSegmentIndex(item_id=item.item_id, definitions=tuple(by_item[item.item_id]))
            for item in items
        )
    except ValueError as exc:
        raise DatasetValidationError(f"invalid segment definitions: {exc}") from exc


def _enforce_limits(
    *,
    limits: LimitConfig,
    items: tuple[SourceItem, ...],
    events: tuple[BehaviorEvent, ...],
    indexes: tuple[ItemSegmentIndex, ...],
) -> None:
    counts = {
        "max_items": len(items),
        "max_behavior_events": len(events),
        "max_total_segments": sum(len(index.definitions) for index in indexes),
        "max_segments_per_item": max((len(index.definitions) for index in indexes), default=0),
    }
    for field_name, count in counts.items():
        if count > getattr(limits, field_name):
            raise DatasetValidationError(f"source exceeds configured {field_name}")


def _artifact_from_payload(
    *,
    ref: ResourceRef,
    payload: bytes,
    artifact_kind: str,
    schema_version: str,
    record_count: int | None,
) -> ArtifactEntry:
    return ArtifactEntry(
        resource_ref=ref,
        artifact_kind=artifact_kind,
        schema_version=schema_version,
        size_bytes=len(payload),
        record_count=record_count,
    )


def _collect_source_artifacts(
    *,
    resolver: FilesystemPathResolver,
    registry: RootRegistry,
    manifest: SourceDatasetManifest,
    items: tuple[SourceItem, ...],
    events: tuple[BehaviorEvent, ...],
    definitions: tuple[SegmentDefinition, ...],
    record_payloads: dict[tuple[str, str, str, str], bytes],
) -> tuple[ArtifactEntry, ...]:
    entries = [
        _artifact_from_payload(
            ref=manifest.behavior_events_ref,
            payload=record_payloads[resource_identity(manifest.behavior_events_ref)],
            artifact_kind="behavior-events",
            schema_version="behavior-event-v1",
            record_count=len(events),
        ),
        _artifact_from_payload(
            ref=manifest.items_ref,
            payload=record_payloads[resource_identity(manifest.items_ref)],
            artifact_kind="source-items",
            schema_version="source-item-v1",
            record_count=len(items),
        ),
        _artifact_from_payload(
            ref=manifest.segment_definitions_ref,
            payload=record_payloads[resource_identity(manifest.segment_definitions_ref)],
            artifact_kind="segment-definitions",
            schema_version="segment-definition-v1",
            record_count=len(definitions),
        ),
    ]
    media_refs: list[ResourceRef] = []
    for definition in definitions:
        media_refs.append(definition.locator.media_ref)
        if isinstance(definition.locator, FileLocator) and definition.locator.origin is not None:
            media_refs.append(definition.locator.origin.original_media_ref)
    seen: dict[tuple[str, str], ResourceRef] = {}
    for media_ref in media_refs:
        logical = (media_ref.store, media_ref.key)
        previous = seen.get(logical)
        if previous is not None and previous != media_ref:
            raise DatasetValidationError(
                f"conflicting declarations for source resource {media_ref.store}/{media_ref.key}"
            )
        seen[logical] = media_ref
    _validate_source_ref_collisions(
        (
            manifest.behavior_events_ref,
            manifest.items_ref,
            manifest.segment_definitions_ref,
            *tuple(seen.values()),
        )
    )
    for media_ref in seen.values():
        _require_read_only(registry, media_ref)
        payload = resolver.read_verified_bytes(media_ref)
        entries.append(
            _artifact_from_payload(
                ref=media_ref,
                payload=payload,
                artifact_kind="media",
                schema_version="opaque-bytes-v1",
                record_count=None,
            )
        )
    return tuple(sorted(entries, key=lambda entry: resource_identity(entry.resource_ref)))


def load_source_dataset(loaded: LoadedPreprocessingConfig) -> LoadedSourceDataset:
    resolver = FilesystemPathResolver(loaded.root_registry)
    _require_read_only(loaded.root_registry, loaded.config.source.manifest_ref)
    manifest_payload = resolver.read_verified_bytes(loaded.config.source.manifest_ref)
    manifest = decode_json(
        manifest_payload,
        SourceDatasetManifest,
        logical_name=loaded.config.source.manifest_ref.key,
    )
    _validate_source_ref_collisions(
        (
            loaded.config.source.manifest_ref,
            manifest.behavior_events_ref,
            manifest.items_ref,
            manifest.segment_definitions_ref,
        )
    )
    for ref in (
        manifest.behavior_events_ref,
        manifest.items_ref,
        manifest.segment_definitions_ref,
    ):
        _require_read_only(loaded.root_registry, ref)
    items_payload = resolver.read_verified_bytes(manifest.items_ref)
    behavior_payload = resolver.read_verified_bytes(manifest.behavior_events_ref)
    definitions_payload = resolver.read_verified_bytes(manifest.segment_definitions_ref)
    items = _validate_items(
        decode_jsonl(
            items_payload,
            SourceItem,
            logical_name=manifest.items_ref.key,
        )
    )
    item_ids = frozenset(entry.item_id for entry in items)
    events = _validate_behaviors(
        decode_jsonl(
            behavior_payload,
            BehaviorEvent,
            logical_name=manifest.behavior_events_ref.key,
        ),
        item_ids,
    )
    definitions = decode_jsonl(
        definitions_payload,
        SegmentDefinition,
        logical_name=manifest.segment_definitions_ref.key,
    )
    for logical_name, payload, records in (
        (manifest.items_ref.key, items_payload, items),
        (manifest.behavior_events_ref.key, behavior_payload, events),
        (manifest.segment_definitions_ref.key, definitions_payload, definitions),
    ):
        if encode_jsonl(records) != payload:
            raise DatasetValidationError(f"source records are not canonical JSONL: {logical_name}")
    indexes = _build_segment_indexes(items, definitions)
    _enforce_limits(limits=loaded.config.limits, items=items, events=events, indexes=indexes)
    artifacts = _collect_source_artifacts(
        resolver=resolver,
        registry=loaded.root_registry,
        manifest=manifest,
        items=items,
        events=events,
        definitions=definitions,
        record_payloads={
            resource_identity(manifest.items_ref): items_payload,
            resource_identity(manifest.behavior_events_ref): behavior_payload,
            resource_identity(manifest.segment_definitions_ref): definitions_payload,
        },
    )
    return LoadedSourceDataset(
        manifest=manifest,
        items=items,
        behavior_events=events,
        segment_definitions=definitions,
        segment_indexes=indexes,
        source_artifacts=artifacts,
    )
