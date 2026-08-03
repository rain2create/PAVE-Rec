from __future__ import annotations

from dataclasses import replace

import pytest

from pave_rec.errors import ComponentExecutionError, DatasetValidationError
from pave_rec.preprocessing.codecs import decode_json, decode_jsonl
from pave_rec.preprocessing.components import (
    CanonicalBehaviorProcessor,
    ManifestSegmentDefinitionProvider,
    StructuralItemFeatureExtractor,
    build_preprocessing_components,
    map_attributes,
)
from pave_rec.preprocessing.config import (
    AttributeMapping,
    PreprocessingComponentConfig,
    load_preprocessing_config,
)
from pave_rec.preprocessing.models import (
    BehaviorEvent,
    RangeLocator,
    SegmentDefinition,
    SourceItem,
)
from pave_rec.preprocessing.source import (
    _build_segment_indexes,
    _validate_behaviors,
    _validate_items,
)


def item(item_id: str) -> SourceItem:
    return SourceItem(item_id=item_id, metadata={})


def event(
    user_id: str = "user",
    item_id: str = "item_a",
    index: int = 0,
    timestamp: int | None = None,
) -> BehaviorEvent:
    return BehaviorEvent(
        user_id=user_id,
        item_id=item_id,
        interaction_index=index,
        occurred_at_ms=timestamp,
        interaction_type="view",
        value=None,
        metadata={},
    )


def definition(item_id: str, sequence_index: int) -> SegmentDefinition:
    from pave_rec.domain import ResourceRef

    return SegmentDefinition(
        item_id=item_id,
        segment_id=f"segment_{sequence_index}",
        sequence_index=sequence_index,
        locator=RangeLocator(
            kind="range",
            media_ref=ResourceRef(
                store="source",
                key=f"media/{item_id}.bin",
                version="v1",
                checksum=f"sha256:{'0' * 64}",
            ),
            start_ms=sequence_index * 10,
            end_ms=(sequence_index + 1) * 10,
        ),
        metadata={},
    )


@pytest.mark.parametrize("payload", [b"not-json", b"{}"])
def test_json_codecs_report_typed_schema_failures(payload: bytes) -> None:
    with pytest.raises(DatasetValidationError, match="invalid items"):
        decode_json(payload, SourceItem, logical_name="items")


def test_jsonl_codec_rejects_blank_and_invalid_lines() -> None:
    with pytest.raises(DatasetValidationError, match="blank line"):
        decode_jsonl(b"\n", SourceItem, logical_name="items.jsonl")
    with pytest.raises(DatasetValidationError, match="line 2"):
        decode_jsonl(
            b'{"item_id":"a","metadata":{}}\nnot-json\n',
            SourceItem,
            logical_name="items.jsonl",
        )


def test_source_item_validation_failure_matrix() -> None:
    with pytest.raises(DatasetValidationError, match="must not be empty"):
        _validate_items(())
    with pytest.raises(DatasetValidationError, match="duplicate"):
        _validate_items((item("a"), item("a")))
    with pytest.raises(DatasetValidationError, match="sorted"):
        _validate_items((item("b"), item("a")))


def test_behavior_validation_failure_matrix() -> None:
    item_ids = frozenset({"item_a", "item_b"})
    with pytest.raises(DatasetValidationError, match="must not be empty"):
        _validate_behaviors((), item_ids)
    with pytest.raises(DatasetValidationError, match="duplicate"):
        _validate_behaviors((event(), event(item_id="item_b")), item_ids)
    with pytest.raises(DatasetValidationError, match="canonical"):
        _validate_behaviors((event("z"), event("a")), item_ids)
    with pytest.raises(DatasetValidationError, match="unknown item"):
        _validate_behaviors((event(item_id="missing"),), item_ids)
    with pytest.raises(DatasetValidationError, match="contiguous"):
        _validate_behaviors((event(index=1),), item_ids)
    with pytest.raises(DatasetValidationError, match="all present or all null"):
        _validate_behaviors((event(index=0), event(index=1, timestamp=10)), item_ids)
    with pytest.raises(DatasetValidationError, match="not monotonic"):
        _validate_behaviors((event(index=0, timestamp=20), event(index=1, timestamp=10)), item_ids)


def test_segment_index_validation_failure_matrix() -> None:
    items = (item("item_a"), item("item_b"))
    with pytest.raises(DatasetValidationError, match="canonical"):
        _build_segment_indexes(
            items,
            (definition("item_b", 0), definition("item_a", 0)),
        )
    with pytest.raises(DatasetValidationError, match="unknown item"):
        _build_segment_indexes(items, (definition("missing", 0),))
    with pytest.raises(DatasetValidationError, match="invalid segment"):
        _build_segment_indexes(items, (definition("item_a", 1),))


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("string", "value"),
        ("integer", 1),
        ("number", 1.5),
        ("boolean", True),
        ("string_list", ["a", "b"]),
        ("integer_list", [1, 2]),
        ("number_list", [1, 2.5]),
    ],
)
def test_all_baseline_attribute_types(value_type: str, value: object) -> None:
    mapping = AttributeMapping(
        source_key="source",
        output_key="output",
        value_type=value_type,
        required=True,
    )
    assert map_attributes({"source": value}, (mapping,)) == {"output": value}


def test_component_contract_failures_are_declared() -> None:
    with pytest.raises(ComponentExecutionError, match="behavior processor"):
        CanonicalBehaviorProcessor().process((event(index=1),))
    with pytest.raises(ComponentExecutionError, match="unknown item"):
        ManifestSegmentDefinitionProvider().build_indexes(
            (item("item_a"),), (definition("missing", 0),)
        )
    with pytest.raises(ComponentExecutionError, match="contract failure"):
        ManifestSegmentDefinitionProvider().build_indexes(
            (item("item_a"),), (definition("item_a", 1),)
        )
    with pytest.raises(ComponentExecutionError, match="coverage"):
        StructuralItemFeatureExtractor().extract((item("item_a"),), (), ())


def test_component_bootstrap_rejects_unvalidated_selector() -> None:
    loaded = load_preprocessing_config("configs/preprocessing/fixture.yaml")
    invalid_selectors = PreprocessingComponentConfig.model_construct(
        behavior_processor="unsupported",
        segment_definition_provider="manifest",
        item_feature_extractor="structural",
        segment_proxy_extractor="structural",
    )
    invalid = replace(
        loaded,
        config=loaded.config.model_copy(update={"components": invalid_selectors}),
    )
    with pytest.raises(ComponentExecutionError, match="unsupported"):
        build_preprocessing_components(invalid.config)
