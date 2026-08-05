"""Strict streaming adapter from Tsinghua attribute-expanded CSV to P2 source records."""

from __future__ import annotations

import csv
import hashlib
import math
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pave_rec.errors import DatasetValidationError
from pave_rec.preprocessing.models import BehaviorEvent, SourceItem

from .models import (
    POSITIVE_RECIPE,
    TSINGHUA_ADAPTER_VERSION,
    SnapshotArtifactIdentity,
    TsinghuaAdapterAudit,
    TsinghuaSnapshotIdentity,
)

INTERACTION_HEADER = (
    "user_id",
    "pid",
    "author_id",
    "category_id",
    "category_level",
    "parent_id",
    "root_id",
    "exposed_time",
    "author_fans_count",
    "watch_time",
    "duration",
    "cvm_like",
    "click",
    "comment",
    "follow",
    "collect",
    "forward",
    "hate",
    "tag_name",
    "title",
    "p_hour",
    "p_date",
    "gender",
    "age",
    "mod_price",
    "fre_city",
    "fre_community_type",
    "fre_city_level",
)
CATEGORY_HEADER = (
    "category_level",
    "category_id",
    "category_name_cn",
    "parent_id",
    "root_id",
    "category_name_en",
)
FEEDBACK_COLUMNS = (
    "cvm_like",
    "click",
    "comment",
    "follow",
    "collect",
    "forward",
    "hate",
)
POSITIVE_ACTION_KEYS = ("like", "comment", "follow", "collect", "forward")

InteractionLabel = Literal[
    "positive_v1",
    "explicit_negative_v1",
    "passive_nonpositive_v1",
]
CategoryIdentity = tuple[int, str, str, str]


@dataclass(frozen=True)
class AdaptedTsinghuaSource:
    items: tuple[SourceItem, ...]
    behavior_events: tuple[BehaviorEvent, ...]
    audit: TsinghuaAdapterAudit


@dataclass(frozen=True)
class _Category:
    level: int
    category_id: str
    name_cn: str
    parent_id: str
    root_id: str
    name_en: str | None


@dataclass
class _ItemAccumulator:
    raw_item_id: str
    raw_author_id: str
    duration: Decimal
    author_fans_counts: set[int] = field(default_factory=set)
    valid_titles: set[str] = field(default_factory=set)
    title_reason: str | None = None
    tags: set[str] = field(default_factory=set)
    tags_invalid: bool = False
    categories: set[CategoryIdentity] = field(default_factory=set)


@dataclass
class _ExposureAccumulator:
    raw_user_id: str
    raw_item_id: str
    exposed_time: int
    first_row_ordinal: int
    watch_time: Decimal
    feedback: tuple[bool, ...]
    duration: Decimal
    row_count: int = 0
    duplicate_row_count: int = 0
    row_fingerprints: set[bytes] = field(default_factory=set)
    calendar_pairs: set[tuple[str, str]] = field(default_factory=set)


def _fail(row_ordinal: int, message: str) -> DatasetValidationError:
    return DatasetValidationError(f"invalid Tsinghua source row {row_ordinal}: {message}")


def _require_raw_identity(value: str, field_name: str, row_ordinal: int) -> str:
    if not value.strip():
        raise _fail(row_ordinal, f"{field_name} must not be empty")
    return value


def _parse_bool(value: str, field_name: str, row_ordinal: int) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise _fail(row_ordinal, f"{field_name} must be True or False")


def _parse_int(value: str, field_name: str, row_ordinal: int, *, positive: bool = False) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise _fail(row_ordinal, f"{field_name} must be an integer") from exc
    if str(parsed) != value or parsed < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise _fail(row_ordinal, f"{field_name} must be a canonical {qualifier} integer")
    return parsed


def _parse_decimal(
    value: str,
    field_name: str,
    row_ordinal: int,
    *,
    positive: bool = False,
) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise _fail(row_ordinal, f"{field_name} must be numeric") from exc
    if not parsed.is_finite() or parsed < (Decimal(0) if not positive else Decimal("0.0")):
        raise _fail(row_ordinal, f"{field_name} must be finite and non-negative")
    if positive and parsed <= 0:
        raise _fail(row_ordinal, f"{field_name} must be positive")
    return parsed


def _contains_control(value: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)


def _normalize_text(value: str, *, max_codepoints: int) -> tuple[str | None, str | None]:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        return None, "missing"
    if _contains_control(normalized) or "\n" in normalized or "\r" in normalized:
        return None, "invalid"
    if len(normalized) > max_codepoints:
        return None, "invalid"
    return normalized, None


def _namespace(kind: str, raw_identity: str) -> str:
    return f"tsv:{kind}:{raw_identity}"


def classify_tsinghua_interaction(event: BehaviorEvent) -> InteractionLabel:
    metadata = event.metadata
    if metadata["hate"] is True:
        return "explicit_negative_v1"
    if event.value is not None and event.value > 3:
        return "positive_v1"
    if any(metadata[key] is True for key in POSITIVE_ACTION_KEYS):
        return "positive_v1"
    return "passive_nonpositive_v1"


def _verify_artifact(root: Path, artifact: SnapshotArtifactIdentity) -> Path:
    path = root.joinpath(*artifact.relative_path.split("/"))
    try:
        stat = path.stat()
    except OSError as exc:
        raise DatasetValidationError(
            f"Tsinghua snapshot artifact is unavailable: {artifact.relative_path}"
        ) from exc
    if not path.is_file() or stat.st_size != artifact.size_bytes:
        raise DatasetValidationError(
            f"Tsinghua snapshot artifact size mismatch: {artifact.relative_path}"
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise DatasetValidationError(
            f"cannot read Tsinghua snapshot artifact: {artifact.relative_path}"
        ) from exc
    if f"sha256:{digest.hexdigest()}" != artifact.checksum:
        raise DatasetValidationError(
            f"Tsinghua snapshot artifact checksum mismatch: {artifact.relative_path}"
        )
    return path


def _load_categories(path: Path) -> tuple[dict[str, _Category], int, int]:
    categories: dict[str, _Category] = {}
    english_conflicts = 0
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise DatasetValidationError("cannot open Tsinghua category mapping") from exc
    with handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CATEGORY_HEADER:
            raise DatasetValidationError("unexpected Tsinghua category mapping header")
        for row_ordinal, row in enumerate(reader, start=2):
            if None in row:
                raise _fail(row_ordinal, "category mapping record arity mismatch")
            category_id = _require_raw_identity(row["category_id"], "category_id", row_ordinal)
            category = _Category(
                level=_parse_int(
                    row["category_level"], "category_level", row_ordinal, positive=True
                ),
                category_id=category_id,
                name_cn=_normalize_required_category_name(
                    row["category_name_cn"], "category_name_cn", row_ordinal
                ),
                parent_id=_require_raw_identity(row["parent_id"], "parent_id", row_ordinal),
                root_id=_require_raw_identity(row["root_id"], "root_id", row_ordinal),
                name_en=_normalize_optional_category_name(row["category_name_en"]),
            )
            previous = categories.get(category_id)
            if previous is None:
                categories[category_id] = category
                continue
            if (
                previous.level,
                previous.category_id,
                previous.name_cn,
                previous.parent_id,
                previous.root_id,
            ) != (
                category.level,
                category.category_id,
                category.name_cn,
                category.parent_id,
                category.root_id,
            ):
                raise _fail(row_ordinal, "conflicting category mapping identity")
            if previous.name_en != category.name_en:
                if previous.name_en is not None and category.name_en is not None:
                    english_conflicts += 1
                categories[category_id] = _Category(
                    level=previous.level,
                    category_id=previous.category_id,
                    name_cn=previous.name_cn,
                    parent_id=previous.parent_id,
                    root_id=previous.root_id,
                    name_en=None,
                )
    if not categories:
        raise DatasetValidationError("Tsinghua category mapping must not be empty")
    missing_parent_count = sum(
        category.level > 1 and category.parent_id not in categories
        for category in categories.values()
    )
    return categories, english_conflicts, missing_parent_count


def _normalize_required_category_name(value: str, field_name: str, row_ordinal: int) -> str:
    normalized, reason = _normalize_text(value, max_codepoints=128)
    if reason is not None or normalized is None:
        raise _fail(row_ordinal, f"{field_name} is invalid")
    return normalized


def _normalize_optional_category_name(value: str) -> str | None:
    normalized, reason = _normalize_text(value, max_codepoints=128)
    return normalized if reason is None else None


def _resolve_category_path(
    category_id: str,
    categories: dict[str, _Category],
    *,
    language: Literal["cn", "en"],
) -> str | None:
    names: list[str] = []
    seen: set[str] = set()
    current_id = category_id
    while True:
        if current_id in seen:
            raise DatasetValidationError("Tsinghua category mapping contains a parent cycle")
        seen.add(current_id)
        try:
            current = categories[current_id]
        except KeyError:
            return None
        name = current.name_cn if language == "cn" else current.name_en
        if name is None:
            return None
        names.append(name)
        if current.level == 1 or current.parent_id == current.category_id:
            break
        current_id = current.parent_id
    return " > ".join(reversed(names))


def _calendar_mismatch(exposure: _ExposureAccumulator) -> bool:
    expected = datetime.fromtimestamp(
        exposure.exposed_time,
        tz=timezone(timedelta(hours=8)),
    )
    expected_pair = (expected.strftime("%Y%m%d"), expected.strftime("%H"))
    return any(pair != expected_pair for pair in exposure.calendar_pairs)


def _float(value: Decimal) -> float:
    converted = float(value)
    if not math.isfinite(converted):
        raise DatasetValidationError("numeric value cannot be represented as a finite float")
    return converted


def _item_from_accumulator(
    accumulator: _ItemAccumulator,
    categories: dict[str, _Category],
) -> tuple[SourceItem, str, bool, bool, bool]:
    metadata: dict[str, object] = {
        "source_adapter": TSINGHUA_ADAPTER_VERSION,
        "author_id": _namespace("author", accumulator.raw_author_id),
        "duration_seconds": _float(accumulator.duration),
    }
    if accumulator.title_reason is not None:
        title_status = accumulator.title_reason
    elif len(accumulator.valid_titles) == 1:
        metadata["title_cn"] = next(iter(accumulator.valid_titles))
        title_status = "available"
    elif not accumulator.valid_titles:
        title_status = "missing"
    else:
        title_status = "conflict"
    tags_available = not accumulator.tags_invalid and bool(accumulator.tags)
    if tags_available:
        metadata["tags"] = sorted(accumulator.tags, key=lambda value: value.encode("utf-8"))
    category_identities = sorted(accumulator.categories)
    if not category_identities:
        raise DatasetValidationError("Tsinghua item has no category coverage")
    chinese_paths = [
        _resolve_category_path(identity[3], categories, language="cn")
        for identity in category_identities
    ]
    complete_chinese_paths = list(dict.fromkeys(path for path in chinese_paths if path))
    if not complete_chinese_paths:
        raise DatasetValidationError("Tsinghua item has no complete Chinese category path")
    metadata["category_paths_cn"] = complete_chinese_paths
    chinese_paths_incomplete = any(path is None for path in chinese_paths)
    english_paths = [
        _resolve_category_path(identity[3], categories, language="en")
        for identity in category_identities
    ]
    english_paths_available = all(path is not None for path in english_paths)
    if english_paths_available:
        metadata["category_paths_en"] = english_paths
    return (
        SourceItem(item_id=_namespace("item", accumulator.raw_item_id), metadata=metadata),
        title_status,
        tags_available,
        english_paths_available,
        chinese_paths_incomplete,
    )


def _new_exposure(row: dict[str, str], row_ordinal: int) -> _ExposureAccumulator:
    raw_user_id = _require_raw_identity(row["user_id"], "user_id", row_ordinal)
    raw_item_id = _require_raw_identity(row["pid"], "pid", row_ordinal)
    return _ExposureAccumulator(
        raw_user_id=raw_user_id,
        raw_item_id=raw_item_id,
        exposed_time=_parse_int(row["exposed_time"], "exposed_time", row_ordinal, positive=True),
        first_row_ordinal=row_ordinal,
        watch_time=_parse_decimal(row["watch_time"], "watch_time", row_ordinal),
        feedback=tuple(_parse_bool(row[name], name, row_ordinal) for name in FEEDBACK_COLUMNS),
        duration=_parse_decimal(row["duration"], "duration", row_ordinal, positive=True),
    )


def _update_exposure(
    exposure: _ExposureAccumulator,
    row: dict[str, str],
    row_ordinal: int,
) -> None:
    watch_time = _parse_decimal(row["watch_time"], "watch_time", row_ordinal)
    feedback = tuple(_parse_bool(row[name], name, row_ordinal) for name in FEEDBACK_COLUMNS)
    duration = _parse_decimal(row["duration"], "duration", row_ordinal, positive=True)
    if (watch_time, feedback) != (exposure.watch_time, exposure.feedback):
        raise _fail(row_ordinal, "feedback conflicts inside one exposure")
    if duration != exposure.duration:
        raise _fail(row_ordinal, "duration conflicts inside one exposure")
    fingerprint = hashlib.sha256(
        "\0".join(row[name] for name in INTERACTION_HEADER).encode()
    ).digest()
    if fingerprint in exposure.row_fingerprints:
        exposure.duplicate_row_count += 1
    exposure.row_fingerprints.add(fingerprint)
    exposure.row_count += 1
    exposure.calendar_pairs.add((row["p_date"], row["p_hour"]))


def _update_item(
    items: dict[str, _ItemAccumulator],
    row: dict[str, str],
    row_ordinal: int,
    categories: dict[str, _Category],
) -> None:
    raw_item_id = _require_raw_identity(row["pid"], "pid", row_ordinal)
    author_id = _require_raw_identity(row["author_id"], "author_id", row_ordinal)
    duration = _parse_decimal(row["duration"], "duration", row_ordinal, positive=True)
    accumulator = items.get(raw_item_id)
    if accumulator is None:
        accumulator = _ItemAccumulator(raw_item_id, author_id, duration)
        items[raw_item_id] = accumulator
    elif (accumulator.raw_author_id, accumulator.duration) != (author_id, duration):
        raise _fail(row_ordinal, "critical author_id/duration conflicts inside one item")
    accumulator.author_fans_counts.add(
        _parse_int(row["author_fans_count"], "author_fans_count", row_ordinal)
    )
    title, title_reason = _normalize_text(row["title"], max_codepoints=512)
    if title_reason is not None:
        accumulator.title_reason = title_reason
    elif title is not None:
        accumulator.valid_titles.add(title)
    tag, tag_reason = _normalize_text(row["tag_name"], max_codepoints=128)
    if tag_reason is not None:
        accumulator.tags_invalid = True
    elif tag is not None:
        accumulator.tags.add(tag)
    category_id = _require_raw_identity(row["category_id"], "category_id", row_ordinal)
    try:
        mapped = categories[category_id]
    except KeyError as exc:
        raise _fail(row_ordinal, "category_id is absent from the pinned mapping") from exc
    category_identity = (
        _parse_int(row["category_level"], "category_level", row_ordinal, positive=True),
        _require_raw_identity(row["root_id"], "root_id", row_ordinal),
        _require_raw_identity(row["parent_id"], "parent_id", row_ordinal),
        category_id,
    )
    if category_identity != (
        mapped.level,
        mapped.root_id,
        mapped.parent_id,
        mapped.category_id,
    ):
        raise _fail(row_ordinal, "category tuple conflicts with the pinned mapping")
    accumulator.categories.add(category_identity)


def _event_from_exposure(exposure: _ExposureAccumulator, interaction_index: int) -> BehaviorEvent:
    like, click, comment, follow, collect, forward, hate = exposure.feedback
    return BehaviorEvent(
        user_id=_namespace("user", exposure.raw_user_id),
        item_id=_namespace("item", exposure.raw_item_id),
        interaction_index=interaction_index,
        occurred_at_ms=exposure.exposed_time * 1000,
        interaction_type="short_video_exposure",
        value=_float(exposure.watch_time),
        metadata={
            "like": like,
            "click": click,
            "comment": comment,
            "follow": follow,
            "collect": collect,
            "forward": forward,
            "hate": hate,
            "effective_view": exposure.watch_time > 3,
            "effective_view_recipe": "watch-time-gt-3-seconds-v1",
            "source_first_logical_row_ordinal": exposure.first_row_ordinal,
        },
    )


def _adapt_interactions(
    path: Path,
    categories: dict[str, _Category],
) -> tuple[tuple[BehaviorEvent, ...], tuple[SourceItem, ...], dict[str, int]]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise DatasetValidationError("cannot open Tsinghua interaction CSV") from exc
    exposures: list[_ExposureAccumulator] = []
    item_accumulators: dict[str, _ItemAccumulator] = {}
    seen_exposure_keys: set[tuple[str, str, int]] = set()
    current: _ExposureAccumulator | None = None
    source_rows = 0
    with handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != INTERACTION_HEADER:
            raise DatasetValidationError("unexpected Tsinghua interaction CSV header")
        for row_ordinal, row in enumerate(reader, start=2):
            source_rows += 1
            if None in row or any(value is None for value in row.values()):
                raise _fail(row_ordinal, "interaction record arity mismatch")
            user_id = _require_raw_identity(row["user_id"], "user_id", row_ordinal)
            item_id = _require_raw_identity(row["pid"], "pid", row_ordinal)
            exposed_time = _parse_int(
                row["exposed_time"], "exposed_time", row_ordinal, positive=True
            )
            key = (user_id, item_id, exposed_time)
            current_key = (
                None
                if current is None
                else (current.raw_user_id, current.raw_item_id, current.exposed_time)
            )
            if key != current_key:
                if key in seen_exposure_keys:
                    raise _fail(row_ordinal, "one exposure appears in non-contiguous row groups")
                if current is not None:
                    exposures.append(current)
                seen_exposure_keys.add(key)
                current = _new_exposure(row, row_ordinal)
            assert current is not None
            _update_exposure(current, row, row_ordinal)
            _update_item(item_accumulators, row, row_ordinal, categories)
    if current is not None:
        exposures.append(current)
    if not exposures:
        raise DatasetValidationError("Tsinghua interaction CSV must not be empty")

    by_user: dict[str, list[_ExposureAccumulator]] = defaultdict(list)
    for exposure in exposures:
        by_user[exposure.raw_user_id].append(exposure)
    events: list[BehaviorEvent] = []
    for raw_user_id in sorted(by_user, key=lambda value: _namespace("user", value)):
        ordered = sorted(
            by_user[raw_user_id],
            key=lambda entry: (entry.exposed_time, entry.first_row_ordinal),
        )
        events.extend(_event_from_exposure(entry, index) for index, entry in enumerate(ordered))

    items: list[SourceItem] = []
    title_counts = defaultdict(int)
    tags_available_count = 0
    english_paths_available_count = 0
    chinese_paths_incomplete_count = 0
    for raw_item_id in sorted(item_accumulators, key=lambda value: _namespace("item", value)):
        (
            item,
            title_status,
            tags_available,
            english_paths_available,
            chinese_paths_incomplete,
        ) = _item_from_accumulator(item_accumulators[raw_item_id], categories)
        items.append(item)
        title_counts[title_status] += 1
        tags_available_count += int(tags_available)
        english_paths_available_count += int(english_paths_available)
        chinese_paths_incomplete_count += int(chinese_paths_incomplete)
    diagnostics = {
        "source_rows": source_rows,
        "duplicate_rows": sum(entry.duplicate_row_count for entry in exposures),
        "max_group_rows": max(entry.row_count for entry in exposures),
        "title_available": title_counts["available"],
        "title_missing": title_counts["missing"],
        "title_invalid": title_counts["invalid"],
        "title_conflict": title_counts["conflict"],
        "tags_available": tags_available_count,
        "tags_invalid": len(items) - tags_available_count,
        "category_paths_en_available": english_paths_available_count,
        "category_paths_cn_incomplete": chinese_paths_incomplete_count,
        "watch_exceeds": sum(entry.watch_time > entry.duration for entry in exposures),
        "calendar_mismatch": sum(_calendar_mismatch(entry) for entry in exposures),
        "mutable_fans": sum(
            len(entry.author_fans_counts) > 1 for entry in item_accumulators.values()
        ),
    }
    return tuple(events), tuple(items), diagnostics


def adapt_tsinghua_snapshot(
    snapshot: TsinghuaSnapshotIdentity,
    source_root: Path,
) -> AdaptedTsinghuaSource:
    """Verify one exact snapshot and adapt it without leaking physical paths."""

    verified = {
        artifact.relative_path: _verify_artifact(source_root, artifact)
        for artifact in snapshot.artifacts
    }
    (
        categories,
        category_mapping_en_conflicts,
        category_mapping_missing_parents,
    ) = _load_categories(verified["categories_cn_en.csv"])
    events, items, diagnostics = _adapt_interactions(
        verified["interaction_sampled.csv"], categories
    )
    label_counts = defaultdict(int)
    for event in events:
        label_counts[classify_tsinghua_interaction(event)] += 1
    audit = TsinghuaAdapterAudit(
        schema_version="tsinghua-adapter-audit-v1",
        snapshot_id=snapshot.snapshot_id,
        adapter_version=TSINGHUA_ADAPTER_VERSION,
        positive_recipe=POSITIVE_RECIPE,
        source_logical_row_count=diagnostics["source_rows"],
        duplicate_expansion_row_count=diagnostics["duplicate_rows"],
        exposure_count=len(events),
        user_count=len({event.user_id for event in events}),
        item_count=len(items),
        max_expansion_rows_per_exposure=diagnostics["max_group_rows"],
        positive_count=label_counts["positive_v1"],
        explicit_negative_count=label_counts["explicit_negative_v1"],
        passive_nonpositive_count=label_counts["passive_nonpositive_v1"],
        title_available_count=diagnostics["title_available"],
        title_missing_count=diagnostics["title_missing"],
        title_invalid_count=diagnostics["title_invalid"],
        title_conflict_count=diagnostics["title_conflict"],
        tags_available_count=diagnostics["tags_available"],
        tags_invalid_count=diagnostics["tags_invalid"],
        category_available_count=len(items),
        category_paths_en_available_count=diagnostics["category_paths_en_available"],
        category_paths_en_missing_count=(len(items) - diagnostics["category_paths_en_available"]),
        category_mapping_en_conflict_count=category_mapping_en_conflicts,
        category_mapping_en_unavailable_count=sum(
            category.name_en is None for category in categories.values()
        ),
        category_mapping_missing_parent_count=category_mapping_missing_parents,
        category_paths_cn_incomplete_item_count=diagnostics["category_paths_cn_incomplete"],
        watch_time_exceeds_duration_count=diagnostics["watch_exceeds"],
        calendar_mismatch_exposure_count=diagnostics["calendar_mismatch"],
        mutable_author_fans_item_count=diagnostics["mutable_fans"],
    )
    return AdaptedTsinghuaSource(items=items, behavior_events=events, audit=audit)
