"""Persistent Store implementations backed only by eager-loaded immutable indexes."""

from __future__ import annotations

from types import MappingProxyType

from pave_rec.domain import ComponentDescriptor, ItemFeatureRef, ItemSegmentCatalog
from pave_rec.errors import ContractError

from .release import LoadedRelease


class FilesystemItemFeatureStore:
    descriptor = ComponentDescriptor(
        role="item_feature_store",
        implementation="FilesystemItemFeatureStore",
        version="filesystem-item-feature-store-v1",
    )

    def __init__(self, loaded_release: LoadedRelease) -> None:
        self._loaded_release = loaded_release
        self._entries = MappingProxyType(
            {entry.item_id: entry for entry in loaded_release.item_feature_index.entries}
        )

    @property
    def loaded_release(self) -> LoadedRelease:
        return self._loaded_release

    def load_refs(self, item_ids: tuple[str, ...]) -> tuple[ItemFeatureRef, ...]:
        try:
            return tuple(self._entries[item_id] for item_id in item_ids)
        except KeyError as exc:
            raise ContractError(f"unknown persistent item feature key: {exc.args[0]}") from exc


class FilesystemSegmentStore:
    descriptor = ComponentDescriptor(
        role="segment_store",
        implementation="FilesystemSegmentStore",
        version="filesystem-segment-store-v1",
    )

    def __init__(self, loaded_release: LoadedRelease) -> None:
        self._loaded_release = loaded_release
        self._entries = MappingProxyType(
            {entry.item_id: entry for entry in loaded_release.segment_store_index.catalogs}
        )

    @property
    def loaded_release(self) -> LoadedRelease:
        return self._loaded_release

    def load_catalog(self, item_ids: tuple[str, ...]) -> tuple[ItemSegmentCatalog, ...]:
        try:
            return tuple(self._entries[item_id] for item_id in item_ids)
        except KeyError as exc:
            raise ContractError(f"unknown persistent segment key: {exc.args[0]}") from exc
