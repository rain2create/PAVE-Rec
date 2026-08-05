"""Authoritative P3-05 item-semantic build lifecycle."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, DatasetValidationError
from pave_rec.preprocessing.codecs import decode_canonical_json
from pave_rec.preprocessing.paths import FilesystemPathResolver
from pave_rec.stores.loaders import ItemFeatureRecordLoader
from pave_rec.stores.release import ReleaseLoader
from pave_rec.stores.resolver import FilesystemResourceResolver

from .artifact import FilesystemItemSemanticPublisher, build_item_semantic_artifact_plan
from .config import load_phase3_item_semantics_config
from .models import BgeM3SnapshotManifest
from .provider import BgeM3EmbeddingProvider
from .text import build_semantic_text


@dataclass(frozen=True)
class ItemSemanticsResult:
    execution_id: str
    outcome: str
    semantic_version: str
    manifest_ref: ResourceRef
    source_item_count: int
    semantic_item_count: int
    unique_semantic_text_count: int


def _execution_id(config_path: Path, release_ref: ResourceRef) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "config_path": config_path.as_posix(),
                "source_release_ref": release_ref.model_dump(mode="json", exclude_none=False),
            },
            pretty=False,
        )
    ).hexdigest()[:16]
    return f"p3-semantics-{digest}"


def build_item_semantics_from_config(
    config_path: str | Path,
    *,
    execution_id: str | None = None,
) -> ItemSemanticsResult:
    loaded = load_phase3_item_semantics_config(config_path)
    config = loaded.config
    actual_execution_id = execution_id or _execution_id(
        loaded.config_path.relative_to(loaded.project_root),
        config.source_release_ref,
    )
    release = ReleaseLoader(loaded.root_registry).load(config.source_release_ref)
    resource_resolver = FilesystemResourceResolver(release)
    record_loader = ItemFeatureRecordLoader(resource_resolver)
    records = []
    for item_ref in release.item_feature_index.entries:
        if item_ref.feature_ref is None:
            raise ArtifactIntegrityError("semantic source item is missing its feature record")
        records.append(record_loader.load(item_ref.feature_ref, expected_item_id=item_ref.item_id))
    specs = tuple(
        spec
        for record in records
        if (
            spec := build_semantic_text(
                record,
                source_data_version=release.data_version,
            )
        )
        is not None
    )
    resolver = FilesystemPathResolver(loaded.root_registry)
    try:
        snapshot_payload = resolver.read_verified_bytes(config.provider.snapshot_manifest_ref)
        snapshot_manifest = decode_canonical_json(
            snapshot_payload,
            BgeM3SnapshotManifest,
            logical_name="BGE-M3 snapshot manifest",
        )
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError("invalid BGE-M3 snapshot manifest") from exc
    model_root = loaded.root_registry.require(config.provider.model_root_id).path
    snapshot_root = model_root.joinpath(*config.provider.model_directory_key.split("/"))
    try:
        resolved_model_root = model_root.resolve(strict=True)
        snapshot_root = snapshot_root.resolve(strict=True)
        snapshot_root.relative_to(resolved_model_root)
    except (OSError, ValueError) as exc:
        raise ArtifactIntegrityError(
            "configured BGE-M3 snapshot directory escaped its model root"
        ) from exc
    if not snapshot_root.is_dir():
        raise ArtifactIntegrityError("configured BGE-M3 snapshot directory is unavailable")
    provider = BgeM3EmbeddingProvider(
        snapshot_root=snapshot_root,
        snapshot_manifest=snapshot_manifest,
        snapshot_checksum=config.provider.snapshot_manifest_ref.checksum or "",
        device=config.operational.device,
        batch_size=config.operational.batch_size,
    )
    unique_texts: dict[str, str] = {}
    for spec in specs:
        previous = unique_texts.get(spec.semantic_text_sha256)
        if previous is not None and previous != spec.semantic_text:
            raise ArtifactIntegrityError("semantic text SHA-256 collision")
        unique_texts[spec.semantic_text_sha256] = spec.semantic_text
    ordered_checksums = tuple(sorted(unique_texts))
    results = provider.encode(tuple(unique_texts[key] for key in ordered_checksums))
    if len(results) != len(ordered_checksums):
        raise ArtifactIntegrityError("semantic embedding provider coverage mismatch")
    plan = build_item_semantic_artifact_plan(
        output_root_id=config.output_root_id,
        source_data_version=release.data_version,
        source_release_ref=release.release_ref,
        source_item_count=len(records),
        specs=specs,
        embeddings_by_text_checksum=dict(zip(ordered_checksums, results, strict=True)),
        model_snapshot_checksum=provider.snapshot_checksum,
    )
    publication = FilesystemItemSemanticPublisher(loaded.root_registry).publish(
        plan,
        execution_id=actual_execution_id,
    )
    return ItemSemanticsResult(
        execution_id=actual_execution_id,
        outcome=publication.outcome,
        semantic_version=plan.semantic_version,
        manifest_ref=publication.manifest_ref,
        source_item_count=len(records),
        semantic_item_count=len(specs),
        unique_semantic_text_count=len(unique_texts),
    )
