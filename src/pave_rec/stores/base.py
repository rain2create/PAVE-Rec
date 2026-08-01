"""Static item-feature and segment-store protocols."""

from typing import Protocol

from pave_rec.domain import ComponentDescriptor, ItemFeatureRef, ItemSegmentCatalog


class ItemFeatureStore(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def load_refs(self, item_ids: tuple[str, ...]) -> tuple[ItemFeatureRef, ...]: ...


class SegmentStore(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def load_catalog(self, item_ids: tuple[str, ...]) -> tuple[ItemSegmentCatalog, ...]: ...
