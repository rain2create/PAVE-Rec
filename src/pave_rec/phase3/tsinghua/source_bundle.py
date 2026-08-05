"""Immutable P2-compatible source bundle construction and publication."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pave_rec.domain import ResourceRef
from pave_rec.domain.base import require_non_empty
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import ArtifactIntegrityError, ArtifactPublicationError
from pave_rec.preprocessing.codecs import encode_json, encode_jsonl
from pave_rec.preprocessing.models import SourceDatasetManifest
from pave_rec.preprocessing.paths import FilesystemPathResolver, RootRegistry
from pave_rec.preprocessing.publisher import publication_staging_key

from .adapter import AdaptedTsinghuaSource
from .models import POSITIVE_RECIPE, TSINGHUA_ADAPTER_VERSION, TsinghuaSnapshotIdentity

SOURCE_BUNDLE_VERSION = "tsinghua-source-bundle-v1"


def _checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _ref(store: str, key: str, version: str, payload: bytes) -> ResourceRef:
    return ResourceRef(store=store, key=key, version=version, checksum=_checksum(payload))


@dataclass(frozen=True)
class TsinghuaSourceBundlePlan:
    source_version: str
    output_root_id: str
    source_manifest: SourceDatasetManifest
    source_manifest_ref: ResourceRef
    audit_ref: ResourceRef
    files: tuple[tuple[ResourceRef, bytes], ...]

    def __post_init__(self) -> None:
        keys = tuple(ref.key for ref, _ in self.files)
        if len(keys) != len(set(keys)) or keys != tuple(sorted(keys)):
            raise ValueError("source bundle files must use unique canonical key order")
        for ref, payload in self.files:
            if ref.store != self.output_root_id or ref.version != self.source_version:
                raise ValueError("source bundle ref identity mismatch")
            if ref.checksum != _checksum(payload):
                raise ValueError("source bundle payload checksum mismatch")


@dataclass(frozen=True)
class SourceBundlePublicationResult:
    outcome: Literal["created", "reused"]
    source_manifest_ref: ResourceRef


def build_tsinghua_source_bundle(
    *,
    snapshot: TsinghuaSnapshotIdentity,
    adapted: AdaptedTsinghuaSource,
    output_root_id: str,
) -> TsinghuaSourceBundlePlan:
    """Build portable source bytes without including a physical path or invocation."""

    require_non_empty(output_root_id, "output_root_id")
    behavior_payload = encode_jsonl(adapted.behavior_events)
    items_payload = encode_jsonl(adapted.items)
    segment_payload = b""
    audit_payload = encode_json(adapted.audit)
    identity = {
        "identity_schema_version": SOURCE_BUNDLE_VERSION,
        "snapshot": snapshot.model_dump(mode="json", exclude_none=False),
        "adapter_version": TSINGHUA_ADAPTER_VERSION,
        "positive_recipe": POSITIVE_RECIPE,
        "record_schema_versions": {
            "audit": adapted.audit.schema_version,
            "behavior": "behavior-event-v1",
            "item": "source-item-v1",
            "segment": "segment-definition-v1",
        },
        "payloads": {
            "adapter_audit.json": _checksum(audit_payload),
            "behavior_events.jsonl": _checksum(behavior_payload),
            "items.jsonl": _checksum(items_payload),
            "segment_definitions.jsonl": _checksum(segment_payload),
        },
        "counts": {
            "behavior_events": len(adapted.behavior_events),
            "items": len(adapted.items),
            "segments": 0,
        },
    }
    digest = hashlib.sha256(canonical_json_bytes(identity, pretty=False)).hexdigest()
    version = f"tsvsrc-{digest}"
    prefix = f"snapshots/{version}"
    behavior_ref = _ref(
        output_root_id,
        f"{prefix}/behavior_events.jsonl",
        version,
        behavior_payload,
    )
    items_ref = _ref(output_root_id, f"{prefix}/items.jsonl", version, items_payload)
    segment_ref = _ref(
        output_root_id,
        f"{prefix}/segment_definitions.jsonl",
        version,
        segment_payload,
    )
    audit_ref = _ref(output_root_id, f"{prefix}/adapter_audit.json", version, audit_payload)
    manifest = SourceDatasetManifest(
        schema_version="tsinghua-source-dataset-manifest-v1",
        source_dataset_id="tsinghua-shortvideo-official-sampled",
        source_dataset_version=version,
        behavior_events_ref=behavior_ref,
        items_ref=items_ref,
        segment_definitions_ref=segment_ref,
        metadata={
            "source_bundle_identity": identity,
            "adapter_audit_ref": audit_ref.model_dump(mode="json", exclude_none=False),
            "redistribution": "local-research-only-pending-explicit-upstream-license",
        },
    )
    manifest_payload = encode_json(manifest)
    manifest_ref = _ref(
        output_root_id,
        f"{prefix}/source_manifest.json",
        version,
        manifest_payload,
    )
    files = tuple(
        sorted(
            (
                (audit_ref, audit_payload),
                (behavior_ref, behavior_payload),
                (items_ref, items_payload),
                (segment_ref, segment_payload),
                (manifest_ref, manifest_payload),
            ),
            key=lambda entry: entry[0].key,
        )
    )
    return TsinghuaSourceBundlePlan(
        source_version=version,
        output_root_id=output_root_id,
        source_manifest=manifest,
        source_manifest_ref=manifest_ref,
        audit_ref=audit_ref,
        files=files,
    )


class FilesystemTsinghuaSourcePublisher:
    def __init__(self, registry: RootRegistry) -> None:
        self._resolver = FilesystemPathResolver(registry)

    def _path(self, root_id: str, key: str) -> Path:
        return self._resolver.resolve_new_path(root_id, key)

    def _verify(self, plan: TsinghuaSourceBundlePlan, directory: Path) -> None:
        prefix = f"snapshots/{plan.source_version}/"
        expected_relatives: set[str] = set()
        for ref, payload in plan.files:
            relative = ref.key.removeprefix(prefix)
            expected_relatives.add(relative)
            try:
                actual = directory.joinpath(*relative.split("/")).read_bytes()
            except OSError as exc:
                raise ArtifactIntegrityError(
                    f"cannot verify Tsinghua source artifact: {relative}"
                ) from exc
            if actual != payload:
                raise ArtifactIntegrityError(f"Tsinghua source artifact mismatch: {relative}")
        try:
            actual_relatives = {
                path.relative_to(directory).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
            }
        except OSError as exc:
            raise ArtifactIntegrityError("cannot inventory Tsinghua source bundle") from exc
        if actual_relatives != expected_relatives:
            raise ArtifactIntegrityError("Tsinghua source bundle inventory mismatch")

    def publish(
        self,
        plan: TsinghuaSourceBundlePlan,
        *,
        execution_id: str,
    ) -> SourceBundlePublicationResult:
        bundle_key = f"snapshots/{plan.source_version}"
        target = self._path(plan.output_root_id, bundle_key)
        if target.exists():
            self._verify(plan, target)
            return SourceBundlePublicationResult("reused", plan.source_manifest_ref)
        stage_key = publication_staging_key(
            plan.output_root_id,
            plan.source_version,
            execution_id,
        )
        stage = self._path(plan.output_root_id, stage_key)
        prefix = f"snapshots/{plan.source_version}/"
        try:
            stage.mkdir(parents=True, exist_ok=False)
            for ref, payload in plan.files:
                relative = ref.key.removeprefix(prefix)
                destination = stage.joinpath(*relative.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            self._verify(plan, stage)
            target.parent.mkdir(parents=True, exist_ok=True)
            stage.rename(target)
        except ArtifactIntegrityError:
            raise
        except OSError as exc:
            if target.exists():
                self._verify(plan, target)
                return SourceBundlePublicationResult("reused", plan.source_manifest_ref)
            raise ArtifactPublicationError("cannot publish Tsinghua source bundle") from exc
        self._verify(plan, target)
        return SourceBundlePublicationResult("created", plan.source_manifest_ref)
