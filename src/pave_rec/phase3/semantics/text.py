"""Canonical Tsinghua item semantic-text construction."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass

from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import DatasetValidationError
from pave_rec.preprocessing.models import ItemFeatureRecord

from .models import SEMANTIC_TEXT_RECIPE


@dataclass(frozen=True)
class SemanticTextSpec:
    prototype_id: str
    item_id: str
    semantic_text: str
    semantic_text_sha256: str
    included_fields: tuple[str, ...]


def _string_list(attributes: dict, key: str) -> tuple[str, ...]:
    value = attributes.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise DatasetValidationError(f"item semantic attribute {key} must be a string list")
    normalized = tuple(unicodedata.normalize("NFC", entry).strip() for entry in value)
    if any(not entry or "\n" in entry or "\r" in entry for entry in normalized):
        raise DatasetValidationError(f"item semantic attribute {key} contains invalid text")
    if len(normalized) != len(set(normalized)):
        raise DatasetValidationError(f"item semantic attribute {key} contains duplicates")
    return normalized


def build_semantic_text(
    record: ItemFeatureRecord,
    *,
    source_data_version: str,
) -> SemanticTextSpec | None:
    attributes = record.attributes
    title_value = attributes.get("title_cn")
    if title_value is not None and not isinstance(title_value, str):
        raise DatasetValidationError("item semantic title_cn must be a string")
    title = (
        unicodedata.normalize("NFC", title_value).strip() if isinstance(title_value, str) else None
    )
    if title is not None and (not title or "\n" in title or "\r" in title):
        raise DatasetValidationError("item semantic title_cn is invalid")
    tags = _string_list(attributes, "tags")
    categories = _string_list(attributes, "category_paths_cn")
    lines: list[str] = []
    included: list[str] = []
    if title:
        lines.append(f"标题：{title}")
        included.append("title_cn")
    if tags:
        lines.append(f"标签：{'；'.join(tags)}")
        included.append("tags")
    if categories:
        lines.append(f"分类：{'；'.join(categories)}")
        included.append("category_paths_cn")
    if not lines:
        return None
    semantic_text = "\n".join(lines)
    text_checksum = f"sha256:{hashlib.sha256(semantic_text.encode('utf-8')).hexdigest()}"
    prototype_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "schema_version": "p3-item-semantic-prototype-identity-v1",
                "source_data_version": source_data_version,
                "item_id": record.item_id,
                "semantic_text_recipe": SEMANTIC_TEXT_RECIPE,
                "semantic_text_sha256": text_checksum,
            },
            pretty=False,
        )
    ).hexdigest()
    return SemanticTextSpec(
        prototype_id=f"p3proto-{prototype_digest}",
        item_id=record.item_id,
        semantic_text=semantic_text,
        semantic_text_sha256=text_checksum,
        included_fields=tuple(included),
    )
