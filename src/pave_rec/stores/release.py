"""Exact immutable Phase 2 release loading and eager index validation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from pave_rec.domain import ResourceRef
from pave_rec.errors import ArtifactIntegrityError, DatasetValidationError
from pave_rec.preprocessing.codecs import decode_canonical_json, decode_jsonl
from pave_rec.preprocessing.identity import data_version, validate_data_version
from pave_rec.preprocessing.models import (
    ArtifactEntry,
    ItemFeatureStoreIndex,
    ReleaseManifest,
    RootBundleManifest,
    SegmentStoreIndex,
    SourceItem,
)
from pave_rec.preprocessing.paths import (
    FilesystemPathResolver,
    RootRegistry,
    require_sha256,
    validate_filesystem_key,
)

ResourceIdentity = tuple[str, str, str, str]


def resource_identity(ref: ResourceRef) -> ResourceIdentity:
    return (ref.store, ref.key, ref.version, ref.checksum or "")


@dataclass(frozen=True)
class LoadedRelease:
    root_registry: RootRegistry
    release_ref: ResourceRef
    release_manifest: ReleaseManifest
    root_manifests: Mapping[str, RootBundleManifest]
    inventory: Mapping[ResourceIdentity, ArtifactEntry]
    item_feature_index: ItemFeatureStoreIndex
    segment_store_index: SegmentStoreIndex

    @property
    def data_version(self) -> str:
        return self.release_manifest.data_version


def _decode_published(payload: bytes, model_type, *, logical_name: str):
    try:
        return decode_canonical_json(payload, model_type, logical_name=logical_name)
    except DatasetValidationError as exc:
        raise ArtifactIntegrityError(f"invalid published {logical_name}: {exc}") from exc


class ReleaseLoader:
    def __init__(self, root_registry: RootRegistry) -> None:
        self._registry = root_registry
        self._paths = FilesystemPathResolver(root_registry)

    def _validate_exact_release_ref(self, ref: ResourceRef) -> None:
        try:
            validate_data_version(ref.version)
            require_sha256(ref.checksum, "release checksum")
            validate_filesystem_key(ref.key)
        except ValueError as exc:
            raise ArtifactIntegrityError(f"invalid exact release ref: {exc}") from exc
        if ref.key != f"releases/{ref.version}.json":
            raise ArtifactIntegrityError("release ref key/version mismatch")

    def _read_entry(self, entry: ArtifactEntry) -> bytes:
        return self._paths.read_verified_bytes(entry.resource_ref, expected_size=entry.size_bytes)

    def _load_root_manifests(self, release: ReleaseManifest) -> Mapping[str, RootBundleManifest]:
        manifests: dict[str, RootBundleManifest] = {}
        digest = release.data_version.removeprefix("p2-")
        for ref in release.root_bundle_manifest_refs:
            try:
                require_sha256(ref.checksum, "root manifest checksum")
            except ValueError as exc:
                raise ArtifactIntegrityError(str(exc)) from exc
            if ref.version != release.data_version:
                raise ArtifactIntegrityError("root manifest version does not match release")
            payload = self._paths.read_verified_bytes(ref)
            manifest = _decode_published(
                payload,
                RootBundleManifest,
                logical_name=f"root manifest {ref.store}/{ref.key}",
            )
            if (
                manifest.root_id != ref.store
                or manifest.data_version != release.data_version
                or manifest.identity_digest != digest
            ):
                raise ArtifactIntegrityError("root manifest identity mismatch")
            if manifest.root_id in manifests:
                raise ArtifactIntegrityError("duplicate root bundle manifest")
            manifests[manifest.root_id] = manifest
        return MappingProxyType(manifests)

    def _build_inventory(
        self,
        release: ReleaseManifest,
        roots: Mapping[str, RootBundleManifest],
    ) -> Mapping[ResourceIdentity, ArtifactEntry]:
        inventory: dict[ResourceIdentity, ArtifactEntry] = {}
        logical_refs: dict[tuple[str, str], ResourceRef] = {}
        entries = [
            *release.identity.source_artifacts,
            *(entry for root in roots.values() for entry in root.artifacts),
        ]
        for entry in entries:
            ref = entry.resource_ref
            try:
                require_sha256(ref.checksum)
                validate_filesystem_key(ref.key)
            except ValueError as exc:
                raise ArtifactIntegrityError(
                    f"invalid release inventory entry {ref.store}/{ref.key}: {exc}"
                ) from exc
            self._registry.require(ref.store)
            logical = (ref.store, ref.key)
            previous = logical_refs.get(logical)
            if previous is not None and previous != ref:
                raise ArtifactIntegrityError(
                    f"conflicting release inventory entry: {ref.store}/{ref.key}"
                )
            logical_refs[logical] = ref
            identity = resource_identity(ref)
            if identity in inventory:
                raise ArtifactIntegrityError(
                    f"duplicate release inventory entry: {ref.store}/{ref.key}"
                )
            inventory[identity] = entry
        return MappingProxyType(inventory)

    @staticmethod
    def _one_kind(
        inventory: Mapping[ResourceIdentity, ArtifactEntry], artifact_kind: str
    ) -> ArtifactEntry:
        matches = tuple(
            entry for entry in inventory.values() if entry.artifact_kind == artifact_kind
        )
        if len(matches) != 1:
            raise ArtifactIntegrityError(f"release requires exactly one {artifact_kind} artifact")
        return matches[0]

    def _load_indexes(
        self, inventory: Mapping[ResourceIdentity, ArtifactEntry]
    ) -> tuple[ItemFeatureStoreIndex, SegmentStoreIndex]:
        item_entry = self._one_kind(inventory, "item-feature-store-index")
        segment_entry = self._one_kind(inventory, "segment-store-index")
        item_index = _decode_published(
            self._read_entry(item_entry),
            ItemFeatureStoreIndex,
            logical_name="item feature store index",
        )
        segment_index = _decode_published(
            self._read_entry(segment_entry),
            SegmentStoreIndex,
            logical_name="segment store index",
        )
        return item_index, segment_index

    def _validate_coverage(
        self,
        *,
        release: ReleaseManifest,
        inventory: Mapping[ResourceIdentity, ArtifactEntry],
        item_index: ItemFeatureStoreIndex,
        segment_index: SegmentStoreIndex,
    ) -> None:
        if (
            item_index.data_version != release.data_version
            or segment_index.data_version != release.data_version
        ):
            raise ArtifactIntegrityError("store index data version mismatch")
        source_entry = self._one_kind(inventory, "source-items")
        source_payload = self._read_entry(source_entry)
        try:
            source_items = decode_jsonl(
                source_payload, SourceItem, logical_name=source_entry.resource_ref.key
            )
        except DatasetValidationError as exc:
            raise ArtifactIntegrityError("published source item catalog is invalid") from exc
        source_ids = tuple(entry.item_id for entry in source_items)
        item_ids = tuple(entry.item_id for entry in item_index.entries)
        segment_ids = tuple(entry.item_id for entry in segment_index.catalogs)
        if source_ids != item_ids or source_ids != segment_ids:
            raise ArtifactIntegrityError("source and persistent Store coverage mismatch")
        for item_ref in item_index.entries:
            if item_ref.feature_ref is not None:
                self._require_inventory_ref(inventory, item_ref.feature_ref)
        for catalog in segment_index.catalogs:
            for segment in catalog.segments:
                self._require_inventory_ref(inventory, segment.media_ref)
            for proxy in catalog.segment_proxy_refs:
                self._require_inventory_ref(inventory, proxy.feature_ref)

    @staticmethod
    def _require_inventory_ref(
        inventory: Mapping[ResourceIdentity, ArtifactEntry], ref: ResourceRef
    ) -> None:
        if resource_identity(ref) not in inventory:
            raise ArtifactIntegrityError(
                f"index reference is outside release inventory: {ref.store}/{ref.key}"
            )

    def load(self, release_ref: ResourceRef) -> LoadedRelease:
        self._validate_exact_release_ref(release_ref)
        release_payload = self._paths.read_verified_bytes(release_ref)
        release = _decode_published(
            release_payload, ReleaseManifest, logical_name="release manifest"
        )
        if release.data_version != release_ref.version:
            raise ArtifactIntegrityError("release manifest/ref version mismatch")
        if data_version(release.identity) != release.data_version:
            raise ArtifactIntegrityError("release embedded DataIdentity digest mismatch")
        roots = self._load_root_manifests(release)
        inventory = self._build_inventory(release, roots)
        item_index, segment_index = self._load_indexes(inventory)
        self._validate_coverage(
            release=release,
            inventory=inventory,
            item_index=item_index,
            segment_index=segment_index,
        )
        return LoadedRelease(
            root_registry=self._registry,
            release_ref=release_ref,
            release_manifest=release,
            root_manifests=roots,
            inventory=inventory,
            item_feature_index=item_index,
            segment_store_index=segment_index,
        )
