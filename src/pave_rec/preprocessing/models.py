"""Strict Phase 2 records, manifests, indexes, and local result objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from pave_rec.domain import (
    ComponentDescriptor,
    ItemFeatureRef,
    ItemSegmentCatalog,
    ResourceRef,
)
from pave_rec.domain.base import (
    FrozenModel,
    JsonObject,
    require_finite,
    require_non_empty,
    require_optional_non_empty,
    require_unique,
)

from .paths import validate_case_collisions


def _validate_non_negative(value: int, field_name: str) -> int:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _resource_identity(ref: ResourceRef) -> tuple[str, str, str, str]:
    return (ref.store, ref.key, ref.version, ref.checksum or "")


class BehaviorEvent(FrozenModel):
    user_id: str
    item_id: str
    interaction_index: int
    occurred_at_ms: int | None
    interaction_type: str
    value: float | None
    metadata: JsonObject

    @field_validator("user_id", "item_id", "interaction_type")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("interaction_index")
    @classmethod
    def _validate_index(cls, value: int) -> int:
        return _validate_non_negative(value, "interaction_index")

    @field_validator("occurred_at_ms")
    @classmethod
    def _validate_timestamp(cls, value: int | None) -> int | None:
        if value is not None:
            _validate_non_negative(value, "occurred_at_ms")
        return value

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: float | None) -> float | None:
        if value is not None:
            return require_finite(value, "value")
        return value


class SourceItem(FrozenModel):
    item_id: str
    metadata: JsonObject

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")


class SourceDatasetManifest(FrozenModel):
    schema_version: str
    source_dataset_id: str
    source_dataset_version: str
    behavior_events_ref: ResourceRef
    items_ref: ResourceRef
    segment_definitions_ref: ResourceRef
    metadata: JsonObject

    @field_validator("schema_version", "source_dataset_id", "source_dataset_version")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)


class SequenceInteraction(FrozenModel):
    item_id: str
    interaction_index: int
    occurred_at_ms: int | None
    interaction_type: str
    value: float | None
    metadata: JsonObject

    @field_validator("item_id", "interaction_type")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("interaction_index")
    @classmethod
    def _validate_index(cls, value: int) -> int:
        return _validate_non_negative(value, "interaction_index")

    @field_validator("occurred_at_ms")
    @classmethod
    def _validate_timestamp(cls, value: int | None) -> int | None:
        if value is not None:
            _validate_non_negative(value, "occurred_at_ms")
        return value

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: float | None) -> float | None:
        if value is not None:
            return require_finite(value, "value")
        return value


class UserBehaviorSequence(FrozenModel):
    user_id: str
    interactions: tuple[SequenceInteraction, ...]
    metadata: JsonObject

    @field_validator("user_id")
    @classmethod
    def _validate_user_id(cls, value: str) -> str:
        return require_non_empty(value, "user_id")

    @model_validator(mode="after")
    def _validate_sequence(self) -> "UserBehaviorSequence":
        indexes = tuple(entry.interaction_index for entry in self.interactions)
        if indexes != tuple(range(len(indexes))):
            raise ValueError("interaction indexes must be contiguous from zero")
        timestamps = tuple(entry.occurred_at_ms for entry in self.interactions)
        if (
            timestamps
            and any(value is None for value in timestamps)
            and any(value is not None for value in timestamps)
        ):
            raise ValueError("one user sequence must use all timestamps or all null timestamps")
        provided = tuple(value for value in timestamps if value is not None)
        if provided != tuple(sorted(provided)):
            raise ValueError("timestamps must be monotonic by interaction index")
        return self


class OriginRange(FrozenModel):
    original_media_ref: ResourceRef
    start_ms: int
    end_ms: int

    @model_validator(mode="after")
    def _validate_interval(self) -> "OriginRange":
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("origin must use a positive half-open interval")
        return self


class FileLocator(FrozenModel):
    kind: Literal["file"]
    media_ref: ResourceRef
    duration_ms: int
    origin: OriginRange | None

    @field_validator("duration_ms")
    @classmethod
    def _validate_duration(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("duration_ms must be positive")
        return value


class RangeLocator(FrozenModel):
    kind: Literal["range"]
    media_ref: ResourceRef
    start_ms: int
    end_ms: int

    @model_validator(mode="after")
    def _validate_interval(self) -> "RangeLocator":
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("range locator must use a positive half-open interval")
        return self


SegmentLocator = Annotated[FileLocator | RangeLocator, Field(discriminator="kind")]


class SegmentDefinition(FrozenModel):
    item_id: str
    segment_id: str
    sequence_index: int
    locator: SegmentLocator
    metadata: JsonObject

    @field_validator("item_id", "segment_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("sequence_index")
    @classmethod
    def _validate_index(cls, value: int) -> int:
        return _validate_non_negative(value, "sequence_index")

    @property
    def duration_ms(self) -> int:
        if isinstance(self.locator, FileLocator):
            return self.locator.duration_ms
        return self.locator.end_ms - self.locator.start_ms


class ItemSegmentIndex(FrozenModel):
    item_id: str
    definitions: tuple[SegmentDefinition, ...]

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")

    @model_validator(mode="after")
    def _validate_definitions(self) -> "ItemSegmentIndex":
        if any(entry.item_id != self.item_id for entry in self.definitions):
            raise ValueError("segment definitions must match index item_id")
        indexes = tuple(entry.sequence_index for entry in self.definitions)
        if indexes != tuple(range(len(indexes))):
            raise ValueError("segment sequence indexes must be contiguous from zero")
        require_unique(tuple(entry.segment_id for entry in self.definitions), "segment IDs")
        return self


class FeaturePayloadRef(FrozenModel):
    name: str
    resource_ref: ResourceRef
    codec: str
    dtype: str | None
    shape: tuple[int, ...] | None
    metadata: JsonObject

    @field_validator("name", "codec")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("dtype")
    @classmethod
    def _validate_dtype(cls, value: str | None) -> str | None:
        return require_optional_non_empty(value, "dtype")

    @field_validator("shape")
    @classmethod
    def _validate_shape(cls, value: tuple[int, ...] | None) -> tuple[int, ...] | None:
        if value is not None and any(dimension < 0 for dimension in value):
            raise ValueError("shape dimensions must be non-negative")
        return value


def _validate_payload_refs(
    payload_refs: tuple[FeaturePayloadRef, ...],
) -> tuple[FeaturePayloadRef, ...]:
    names = tuple(entry.name for entry in payload_refs)
    require_unique(names, "payload names")
    expected = tuple(
        sorted(
            payload_refs, key=lambda entry: (entry.name, *(_resource_identity(entry.resource_ref)))
        )
    )
    if payload_refs != expected:
        raise ValueError("payload refs must use canonical name/resource order")
    return payload_refs


class ItemFeatureRecord(FrozenModel):
    schema_version: str
    item_id: str
    attributes: JsonObject
    segment_count: int
    payload_refs: tuple[FeaturePayloadRef, ...]
    metadata: JsonObject

    @field_validator("schema_version", "item_id")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("segment_count")
    @classmethod
    def _validate_count(cls, value: int) -> int:
        return _validate_non_negative(value, "segment_count")

    @field_validator("payload_refs")
    @classmethod
    def _validate_payloads(
        cls, value: tuple[FeaturePayloadRef, ...]
    ) -> tuple[FeaturePayloadRef, ...]:
        return _validate_payload_refs(value)


class SegmentProxyRecord(FrozenModel):
    schema_version: str
    item_id: str
    segment_id: str
    duration_ms: int
    sequence_index: int
    segment_count: int
    attributes: JsonObject
    payload_refs: tuple[FeaturePayloadRef, ...]
    metadata: JsonObject

    @field_validator("schema_version", "item_id", "segment_id")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("duration_ms")
    @classmethod
    def _validate_duration(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("duration_ms must be positive")
        return value

    @field_validator("payload_refs")
    @classmethod
    def _validate_payloads(
        cls, value: tuple[FeaturePayloadRef, ...]
    ) -> tuple[FeaturePayloadRef, ...]:
        return _validate_payload_refs(value)

    @model_validator(mode="after")
    def _validate_position(self) -> "SegmentProxyRecord":
        if self.segment_count <= 0:
            raise ValueError("segment_count must be positive for a segment proxy")
        if not 0 <= self.sequence_index < self.segment_count:
            raise ValueError("sequence_index must be inside segment_count")
        return self


class ArtifactEntry(FrozenModel):
    resource_ref: ResourceRef
    artifact_kind: str
    schema_version: str
    size_bytes: int
    record_count: int | None

    @field_validator("artifact_kind", "schema_version")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("size_bytes")
    @classmethod
    def _validate_size(cls, value: int) -> int:
        return _validate_non_negative(value, "size_bytes")

    @field_validator("record_count")
    @classmethod
    def _validate_record_count(cls, value: int | None) -> int | None:
        if value is not None:
            _validate_non_negative(value, "record_count")
        return value


class DataIdentity(FrozenModel):
    identity_schema_version: str
    source_manifest: SourceDatasetManifest
    source_artifacts: tuple[ArtifactEntry, ...]
    semantic_config: JsonObject
    component_descriptors: tuple[ComponentDescriptor, ...]
    output_versions: JsonObject

    @field_validator("identity_schema_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        return require_non_empty(value, "identity_schema_version")

    @model_validator(mode="after")
    def _validate_identity(self) -> "DataIdentity":
        source_refs = tuple(entry.resource_ref for entry in self.source_artifacts)
        expected_sources = tuple(
            sorted(self.source_artifacts, key=lambda entry: _resource_identity(entry.resource_ref))
        )
        if self.source_artifacts != expected_sources:
            raise ValueError("source artifacts must use canonical ResourceRef order")
        require_unique(tuple(_resource_identity(ref) for ref in source_refs), "source artifacts")
        roles = tuple(entry.role for entry in self.component_descriptors)
        require_unique(roles, "component descriptor roles")
        return self


class RootBundleManifest(FrozenModel):
    schema_version: str
    data_version: str
    root_id: str
    identity_digest: str
    artifacts: tuple[ArtifactEntry, ...]

    @field_validator("schema_version", "data_version", "root_id", "identity_digest")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_artifacts(self) -> "RootBundleManifest":
        expected = tuple(
            sorted(
                self.artifacts,
                key=lambda entry: (entry.resource_ref.store, entry.resource_ref.key),
            )
        )
        if self.artifacts != expected:
            raise ValueError("root artifacts must use canonical store/key order")
        keys = tuple((entry.resource_ref.store, entry.resource_ref.key) for entry in self.artifacts)
        require_unique(keys, "root artifact keys")
        validate_case_collisions(tuple(entry.resource_ref.key for entry in self.artifacts))
        if any(entry.resource_ref.store != self.root_id for entry in self.artifacts):
            raise ValueError("root artifacts must match manifest root_id")
        return self


class ReleaseManifest(FrozenModel):
    schema_version: str
    data_version: str
    identity: DataIdentity
    root_bundle_manifest_refs: tuple[ResourceRef, ...]
    status: Literal["complete"]

    @field_validator("schema_version", "data_version")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_root_refs(self) -> "ReleaseManifest":
        expected = tuple(
            sorted(self.root_bundle_manifest_refs, key=lambda ref: (ref.store, ref.key))
        )
        if self.root_bundle_manifest_refs != expected:
            raise ValueError("root manifest refs must use canonical store/key order")
        require_unique(
            tuple((ref.store, ref.key) for ref in self.root_bundle_manifest_refs),
            "root manifest refs",
        )
        refs_by_root: dict[str, list[str]] = {}
        for ref in self.root_bundle_manifest_refs:
            refs_by_root.setdefault(ref.store, []).append(ref.key)
        for keys in refs_by_root.values():
            validate_case_collisions(tuple(keys))
        return self


class ItemFeatureStoreIndex(FrozenModel):
    schema_version: str
    data_version: str
    entries: tuple[ItemFeatureRef, ...]

    @field_validator("schema_version", "data_version")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_entries(self) -> "ItemFeatureStoreIndex":
        item_ids = tuple(entry.item_id for entry in self.entries)
        require_unique(item_ids, "item feature index IDs")
        if item_ids != tuple(sorted(item_ids)):
            raise ValueError("item feature index must be sorted by item_id")
        return self


class SegmentStoreIndex(FrozenModel):
    schema_version: str
    data_version: str
    catalogs: tuple[ItemSegmentCatalog, ...]

    @field_validator("schema_version", "data_version")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_catalogs(self) -> "SegmentStoreIndex":
        item_ids = tuple(entry.item_id for entry in self.catalogs)
        require_unique(item_ids, "segment store index IDs")
        if item_ids != tuple(sorted(item_ids)):
            raise ValueError("segment store index must be sorted by item_id")
        return self


class ExecutionRootRecord(FrozenModel):
    root_id: str
    configured_path: str
    resolved_path: str
    access: Literal["read_only", "write_new"]

    @field_validator("root_id", "configured_path", "resolved_path")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)


class ExecutionReport(FrozenModel):
    schema_version: str
    execution_id: str
    status: Literal["succeeded", "failed"]
    outcome: Literal["created", "reused"] | None
    data_version: str | None
    release_ref: ResourceRef | None
    started_at_utc: str
    completed_at_utc: str
    config_path: str
    roots: tuple[ExecutionRootRecord, ...]
    component_descriptors: tuple[ComponentDescriptor, ...]
    git_commit: str | None
    git_dirty: bool | None
    python_version: str
    pave_rec_version: str | None
    pydantic_version: str
    pyyaml_version: str
    platform: str
    item_count: int | None
    behavior_event_count: int | None
    segment_count: int | None
    artifact_count: int | None
    staging_locations: tuple[str, ...]
    error_code: str | None
    error_message: str | None

    @field_validator(
        "schema_version",
        "execution_id",
        "started_at_utc",
        "completed_at_utc",
        "config_path",
        "python_version",
        "pydantic_version",
        "pyyaml_version",
        "platform",
    )
    @classmethod
    def _validate_required_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_terminal_state(self) -> "ExecutionReport":
        if self.status == "succeeded":
            if self.outcome is None or self.data_version is None or self.release_ref is None:
                raise ValueError(
                    "successful execution report requires release outcome and identity"
                )
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("successful execution report cannot contain an error")
        else:
            if self.outcome is not None or self.release_ref is not None:
                raise ValueError("failed execution report cannot claim a release outcome")
            if self.error_code is None or self.error_message is None:
                raise ValueError("failed execution report requires a safe error")
        return self


@dataclass(frozen=True)
class PreprocessingResult:
    execution_id: str
    outcome: Literal["created", "reused"]
    data_version: str
    release_ref: ResourceRef
    execution_report_path: Path
    item_count: int
    behavior_event_count: int
    segment_count: int
    artifact_count: int
