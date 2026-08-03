"""Pure replaceable Phase 2 preprocessing component protocols and baselines."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from pave_rec.domain import ComponentDescriptor, SegmentMeta
from pave_rec.errors import ComponentExecutionError, DatasetValidationError

from .config import AttributeMapping, Phase2PreprocessingConfig
from .models import (
    BehaviorEvent,
    FileLocator,
    ItemFeatureRecord,
    ItemSegmentIndex,
    SegmentDefinition,
    SegmentProxyRecord,
    SequenceInteraction,
    SourceItem,
    UserBehaviorSequence,
)


class BehaviorProcessor(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def process(self, events: tuple[BehaviorEvent, ...]) -> tuple[UserBehaviorSequence, ...]: ...


class SegmentDefinitionProvider(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def build_indexes(
        self,
        items: tuple[SourceItem, ...],
        definitions: tuple[SegmentDefinition, ...],
    ) -> tuple[ItemSegmentIndex, ...]: ...


class ItemFeatureExtractor(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def extract(
        self,
        items: tuple[SourceItem, ...],
        indexes: tuple[ItemSegmentIndex, ...],
        mappings: tuple[AttributeMapping, ...],
    ) -> tuple[ItemFeatureRecord, ...]: ...


class SegmentProxyExtractor(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def extract(
        self,
        indexes: tuple[ItemSegmentIndex, ...],
        mappings: tuple[AttributeMapping, ...],
    ) -> tuple[SegmentProxyRecord, ...]: ...


class CanonicalBehaviorProcessor:
    descriptor = ComponentDescriptor(
        role="behavior_processor",
        implementation="CanonicalBehaviorProcessor",
        version="canonical-behavior-v1",
    )

    def process(self, events: tuple[BehaviorEvent, ...]) -> tuple[UserBehaviorSequence, ...]:
        grouped: dict[str, list[BehaviorEvent]] = {}
        for event in events:
            grouped.setdefault(event.user_id, []).append(event)
        try:
            return tuple(
                UserBehaviorSequence(
                    user_id=user_id,
                    interactions=tuple(
                        SequenceInteraction(
                            item_id=event.item_id,
                            interaction_index=event.interaction_index,
                            occurred_at_ms=event.occurred_at_ms,
                            interaction_type=event.interaction_type,
                            value=event.value,
                            metadata=event.metadata,
                        )
                        for event in grouped[user_id]
                    ),
                    metadata={},
                )
                for user_id in sorted(grouped)
            )
        except ValueError as exc:
            raise ComponentExecutionError(f"behavior processor contract failure: {exc}") from exc


class ManifestSegmentDefinitionProvider:
    descriptor = ComponentDescriptor(
        role="segment_definition_provider",
        implementation="ManifestSegmentDefinitionProvider",
        version="manifest-segments-v1",
    )

    def build_indexes(
        self,
        items: tuple[SourceItem, ...],
        definitions: tuple[SegmentDefinition, ...],
    ) -> tuple[ItemSegmentIndex, ...]:
        grouped: dict[str, list[SegmentDefinition]] = {item.item_id: [] for item in items}
        try:
            for definition in definitions:
                grouped[definition.item_id].append(definition)
        except KeyError as exc:
            raise ComponentExecutionError(
                f"segment provider received unknown item: {exc.args[0]}"
            ) from exc
        try:
            return tuple(
                ItemSegmentIndex(item_id=item.item_id, definitions=tuple(grouped[item.item_id]))
                for item in items
            )
        except ValueError as exc:
            raise ComponentExecutionError(f"segment provider contract failure: {exc}") from exc


def _matches_type(value: object, value_type: str) -> bool:
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "integer":
        return type(value) is int
    if value_type == "number":
        return type(value) in {int, float} and isfinite(value)
    if value_type == "boolean":
        return type(value) is bool
    if not isinstance(value, list):
        return False
    if value_type == "string_list":
        return all(isinstance(entry, str) for entry in value)
    if value_type == "integer_list":
        return all(type(entry) is int for entry in value)
    if value_type == "number_list":
        return all(type(entry) in {int, float} and isfinite(entry) for entry in value)
    return False


def map_attributes(
    metadata: Mapping[str, object], mappings: tuple[AttributeMapping, ...]
) -> dict[str, object]:
    attributes: dict[str, object] = {}
    for mapping in mappings:
        value = metadata.get(mapping.source_key)
        if value is None:
            if mapping.required:
                raise DatasetValidationError(f"required attribute is missing: {mapping.source_key}")
            continue
        if not _matches_type(value, mapping.value_type):
            raise DatasetValidationError(
                f"attribute {mapping.source_key} does not match {mapping.value_type}"
            )
        attributes[mapping.output_key] = value
    return attributes


class StructuralItemFeatureExtractor:
    descriptor = ComponentDescriptor(
        role="item_feature_extractor",
        implementation="StructuralItemFeatureExtractor",
        version="structural-item-v1",
    )

    def extract(
        self,
        items: tuple[SourceItem, ...],
        indexes: tuple[ItemSegmentIndex, ...],
        mappings: tuple[AttributeMapping, ...],
    ) -> tuple[ItemFeatureRecord, ...]:
        index_by_item = {entry.item_id: entry for entry in indexes}
        if set(index_by_item) != {item.item_id for item in items}:
            raise ComponentExecutionError("item extractor index coverage mismatch")
        return tuple(
            ItemFeatureRecord(
                schema_version="item-feature-v1",
                item_id=item.item_id,
                attributes=map_attributes(item.metadata, mappings),
                segment_count=len(index_by_item[item.item_id].definitions),
                payload_refs=(),
                metadata={},
            )
            for item in items
        )


class StructuralSegmentProxyExtractor:
    descriptor = ComponentDescriptor(
        role="segment_proxy_extractor",
        implementation="StructuralSegmentProxyExtractor",
        version="structural-segment-proxy-v1",
    )

    def extract(
        self,
        indexes: tuple[ItemSegmentIndex, ...],
        mappings: tuple[AttributeMapping, ...],
    ) -> tuple[SegmentProxyRecord, ...]:
        return tuple(
            SegmentProxyRecord(
                schema_version="segment-proxy-v1",
                item_id=index.item_id,
                segment_id=definition.segment_id,
                duration_ms=definition.duration_ms,
                sequence_index=definition.sequence_index,
                segment_count=len(index.definitions),
                attributes=map_attributes(definition.metadata, mappings),
                payload_refs=(),
                metadata={},
            )
            for index in indexes
            for definition in index.definitions
        )


@dataclass(frozen=True)
class PreprocessingComponents:
    behavior_processor: BehaviorProcessor
    segment_definition_provider: SegmentDefinitionProvider
    item_feature_extractor: ItemFeatureExtractor
    segment_proxy_extractor: SegmentProxyExtractor

    @property
    def descriptors(self) -> tuple[ComponentDescriptor, ...]:
        return (
            self.behavior_processor.descriptor,
            self.segment_definition_provider.descriptor,
            self.item_feature_extractor.descriptor,
            self.segment_proxy_extractor.descriptor,
        )


def build_preprocessing_components(config: Phase2PreprocessingConfig) -> PreprocessingComponents:
    selectors = config.components
    if (
        selectors.behavior_processor != "canonical"
        or selectors.segment_definition_provider != "manifest"
        or selectors.item_feature_extractor != "structural"
        or selectors.segment_proxy_extractor != "structural"
    ):
        raise ComponentExecutionError("unsupported preprocessing component selector")
    return PreprocessingComponents(
        behavior_processor=CanonicalBehaviorProcessor(),
        segment_definition_provider=ManifestSegmentDefinitionProvider(),
        item_feature_extractor=StructuralItemFeatureExtractor(),
        segment_proxy_extractor=StructuralSegmentProxyExtractor(),
    )


def project_segment_meta(definition: SegmentDefinition) -> SegmentMeta:
    locator = definition.locator
    if isinstance(locator, FileLocator):
        start_ms = 0
        end_ms = locator.duration_ms
    else:
        start_ms = locator.start_ms
        end_ms = locator.end_ms
    return SegmentMeta(
        item_id=definition.item_id,
        segment_id=definition.segment_id,
        start_ms=start_ms,
        end_ms=end_ms,
        media_ref=locator.media_ref,
        metadata={},
    )
