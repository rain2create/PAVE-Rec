from __future__ import annotations

from dataclasses import replace

import pytest

from pave_rec.domain import ComponentDescriptor
from pave_rec.errors import DatasetValidationError
from pave_rec.preprocessing.codecs import decode_canonical_json, encode_json, encode_jsonl
from pave_rec.preprocessing.components import (
    build_preprocessing_components,
    map_attributes,
    project_segment_meta,
)
from pave_rec.preprocessing.config import AttributeMapping, LimitConfig, load_preprocessing_config
from pave_rec.preprocessing.identity import (
    build_data_identity,
    canonical_manifest_semantics,
    data_version,
    item_feature_key,
    item_identity_hash,
    segment_identity_hash,
    segment_proxy_key,
    validate_data_version,
)
from pave_rec.preprocessing.models import ItemFeatureRecord
from pave_rec.preprocessing.source import load_source_dataset


def load_fixture():
    loaded = load_preprocessing_config("configs/preprocessing/fixture.yaml")
    return loaded, load_source_dataset(loaded)


def test_canonical_fixture_ingestion_has_expected_coverage() -> None:
    loaded, source = load_fixture()
    assert len(source.items) == 3
    assert len(source.behavior_events) == 6
    assert len(source.segment_definitions) == 6
    assert len(source.source_artifacts) == 10
    assert tuple(entry.item_id for entry in source.segment_indexes) == (
        "item_a",
        "item_b",
        "item_c",
    )
    assert loaded.root_registry.require("source").access == "read_only"


def test_behavior_processor_preserves_repeats_and_null_timestamp_mode() -> None:
    loaded, source = load_fixture()
    components = build_preprocessing_components(loaded.config)
    sequences = components.behavior_processor.process(source.behavior_events)
    assert tuple(entry.user_id for entry in sequences) == ("user_timed", "user_without_time")
    assert tuple(event.item_id for event in sequences[0].interactions) == (
        "item_a",
        "item_a",
        "item_b",
    )
    assert all(event.occurred_at_ms is None for event in sequences[1].interactions)
    assert encode_jsonl(sequences).endswith(b"\n")


def test_structural_extractors_and_p1_projection() -> None:
    loaded, source = load_fixture()
    components = build_preprocessing_components(loaded.config)
    indexes = components.segment_definition_provider.build_indexes(
        source.items, source.segment_definitions
    )
    items = components.item_feature_extractor.extract(
        source.items, indexes, loaded.config.features.item_attributes
    )
    proxies = components.segment_proxy_extractor.extract(
        indexes, loaded.config.features.segment_attributes
    )
    assert [entry.attributes for entry in items] == [
        {"category": "drama"},
        {"category": "thriller"},
        {},
    ]
    assert len(proxies) == 6
    assert proxies[0].duration_ms == 10_000
    file_meta = project_segment_meta(indexes[0].definitions[1])
    range_meta = project_segment_meta(indexes[0].definitions[0])
    assert (file_meta.start_ms, file_meta.end_ms) == (0, 15_000)
    assert (range_meta.start_ms, range_meta.end_ms) == (0, 10_000)


def test_attribute_mapping_has_no_coercion_or_defaults() -> None:
    optional = (
        AttributeMapping(
            source_key="missing",
            output_key="missing",
            value_type="string",
            required=False,
        ),
    )
    assert map_attributes({}, optional) == {}
    required = (optional[0].model_copy(update={"required": True}),)
    with pytest.raises(DatasetValidationError, match="required"):
        map_attributes({}, required)
    integer = (
        AttributeMapping(
            source_key="count", output_key="count", value_type="integer", required=True
        ),
    )
    with pytest.raises(DatasetValidationError, match="does not match"):
        map_attributes({"count": True}, integer)


def test_data_identity_excludes_non_binding_limits_and_changes_with_semantics() -> None:
    loaded, source = load_fixture()
    components = build_preprocessing_components(loaded.config)
    original = build_data_identity(
        source=source,
        config=loaded.config,
        component_descriptors=components.descriptors,
    )
    raised_limits = loaded.config.model_copy(
        update={
            "limits": LimitConfig(
                max_items=1000,
                max_behavior_events=2000,
                max_total_segments=3000,
                max_segments_per_item=1000,
            )
        }
    )
    same = build_data_identity(
        source=source,
        config=raised_limits,
        component_descriptors=components.descriptors,
    )
    assert data_version(original) == data_version(same)
    changed_descriptors = (
        components.descriptors[0].model_copy(update={"version": "canonical-behavior-v2"}),
        *components.descriptors[1:],
    )
    changed = build_data_identity(
        source=source,
        config=loaded.config,
        component_descriptors=changed_descriptors,
    )
    assert data_version(original) != data_version(changed)
    changed_mapping = loaded.config.model_copy(
        update={
            "features": loaded.config.features.model_copy(
                update={
                    "item_attributes": (
                        loaded.config.features.item_attributes[0].model_copy(
                            update={"output_key": "renamed_category"}
                        ),
                    )
                }
            )
        }
    )
    mapping_identity = build_data_identity(
        source=source,
        config=changed_mapping,
        component_descriptors=components.descriptors,
    )
    assert data_version(original) != data_version(mapping_identity)
    assert data_version(original) != data_version(
        original.model_copy(update={"output_versions": {"schema": "future-v2"}})
    )
    assert data_version(original) != data_version(
        original.model_copy(
            update={
                "source_manifest": original.source_manifest.model_copy(
                    update={"source_dataset_version": "preprocessing-v2"}
                )
            }
        )
    )
    validate_data_version(data_version(original))
    with pytest.raises(ValueError):
        validate_data_version("p2-short")


def test_source_manifest_identity_ignores_json_formatting() -> None:
    _, source = load_fixture()
    compact = canonical_manifest_semantics(source.manifest)
    pretty = encode_json(source.manifest)
    assert compact != pretty
    assert canonical_manifest_semantics(source.manifest) == compact


def test_identity_hashes_use_full_digest_and_safe_paths() -> None:
    item_hash = item_identity_hash("item/unsafe")
    segment_hash = segment_identity_hash("item/unsafe", "../segment")
    assert len(item_hash) == len(segment_hash) == 64
    item_key = item_feature_key("p2-version", "item/unsafe")
    segment_key = segment_proxy_key("p2-version", "item/unsafe", "../segment")
    assert "item/unsafe" not in item_key
    assert "../segment" not in segment_key


def test_canonical_typed_loader_rejects_noncanonical_generated_json() -> None:
    record = ItemFeatureRecord(
        schema_version="item-feature-v1",
        item_id="item",
        attributes={},
        segment_count=0,
        payload_refs=(),
        metadata={},
    )
    canonical = encode_json(record)
    assert (
        decode_canonical_json(canonical, ItemFeatureRecord, logical_name="item.json").item_id
        == "item"
    )
    with pytest.raises(DatasetValidationError, match="canonical"):
        decode_canonical_json(
            canonical.replace(b"  ", b"    ", 1),
            ItemFeatureRecord,
            logical_name="item.json",
        )


def test_component_descriptor_order_is_fixed() -> None:
    loaded, _ = load_fixture()
    descriptors = build_preprocessing_components(loaded.config).descriptors
    assert tuple(entry.role for entry in descriptors) == (
        "behavior_processor",
        "segment_definition_provider",
        "item_feature_extractor",
        "segment_proxy_extractor",
    )
    assert all(isinstance(entry, ComponentDescriptor) for entry in descriptors)


def test_count_limits_fail_without_truncation() -> None:
    loaded, _ = load_fixture()
    limited = replace(
        loaded,
        config=loaded.config.model_copy(
            update={"limits": loaded.config.limits.model_copy(update={"max_behavior_events": 5})}
        ),
    )
    with pytest.raises(DatasetValidationError, match="max_behavior_events"):
        load_source_dataset(limited)
