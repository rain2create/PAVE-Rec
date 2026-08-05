"""Authoritative Python lifecycle for pinned Tsinghua source adaptation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes

from .adapter import adapt_tsinghua_snapshot
from .config import load_tsinghua_source_adapter_config
from .source_bundle import FilesystemTsinghuaSourcePublisher, build_tsinghua_source_bundle


@dataclass(frozen=True)
class TsinghuaSourceAdapterResult:
    execution_id: str
    outcome: str
    source_version: str
    source_manifest_ref: ResourceRef
    item_count: int
    behavior_event_count: int


def _execution_id(config_path: Path, snapshot_id: str) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {"config_path": config_path.as_posix(), "snapshot_id": snapshot_id},
            pretty=False,
        )
    ).hexdigest()[:16]
    return f"tsv-adapt-{digest}"


def adapt_tsinghua_from_config(
    config_path: str | Path,
    *,
    execution_id: str | None = None,
) -> TsinghuaSourceAdapterResult:
    loaded = load_tsinghua_source_adapter_config(config_path)
    config = loaded.config
    actual_execution_id = execution_id or _execution_id(
        loaded.config_path.relative_to(loaded.project_root), config.snapshot.snapshot_id
    )
    source_root = loaded.root_registry.require(config.source_root_id).path
    adapted = adapt_tsinghua_snapshot(config.snapshot, source_root)
    plan = build_tsinghua_source_bundle(
        snapshot=config.snapshot,
        adapted=adapted,
        output_root_id=config.output_root_id,
    )
    publication = FilesystemTsinghuaSourcePublisher(loaded.root_registry).publish(
        plan,
        execution_id=actual_execution_id,
    )
    return TsinghuaSourceAdapterResult(
        execution_id=actual_execution_id,
        outcome=publication.outcome,
        source_version=plan.source_version,
        source_manifest_ref=publication.source_manifest_ref,
        item_count=len(adapted.items),
        behavior_event_count=len(adapted.behavior_events),
    )
