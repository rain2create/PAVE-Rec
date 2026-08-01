"""Deterministic in-memory stores backed by validated fixture entries."""

from pave_rec.domain import ComponentDescriptor, ItemFeatureRef, ItemSegmentCatalog
from pave_rec.errors import ContractError


class InMemoryItemFeatureStore:
    descriptor = ComponentDescriptor(
        role="item_feature_store",
        implementation="InMemoryItemFeatureStore",
        version="mock-v1",
    )

    def __init__(self, entries: tuple[ItemFeatureRef, ...]) -> None:
        self._entries = {entry.item_id: entry for entry in entries}

    def load_refs(self, item_ids: tuple[str, ...]) -> tuple[ItemFeatureRef, ...]:
        try:
            return tuple(self._entries[item_id] for item_id in item_ids)
        except KeyError as exc:
            raise ContractError(f"unknown item feature fixture key: {exc.args[0]}") from exc


class InMemorySegmentStore:
    descriptor = ComponentDescriptor(
        role="segment_store", implementation="InMemorySegmentStore", version="mock-v1"
    )

    def __init__(self, entries: tuple[ItemSegmentCatalog, ...]) -> None:
        self._entries = {entry.item_id: entry for entry in entries}

    def load_catalog(self, item_ids: tuple[str, ...]) -> tuple[ItemSegmentCatalog, ...]:
        try:
            return tuple(self._entries[item_id] for item_id in item_ids)
        except KeyError as exc:
            raise ContractError(f"unknown segment fixture key: {exc.args[0]}") from exc
