"""Typed decoders layered over verified release-scoped resource bytes."""

from __future__ import annotations

from pave_rec.domain import ResourceRef
from pave_rec.errors import ArtifactIntegrityError, DatasetValidationError
from pave_rec.preprocessing.codecs import decode_canonical_json
from pave_rec.preprocessing.models import ItemFeatureRecord, SegmentProxyRecord

from .resolver import ResourceResolver


class ItemFeatureRecordLoader:
    def __init__(self, resolver: ResourceResolver) -> None:
        self._resolver = resolver

    def load(self, ref: ResourceRef, *, expected_item_id: str) -> ItemFeatureRecord:
        try:
            record = decode_canonical_json(
                self._resolver.read_verified_bytes(ref),
                ItemFeatureRecord,
                logical_name=f"item feature {expected_item_id}",
            )
        except DatasetValidationError as exc:
            raise ArtifactIntegrityError(
                f"invalid item feature record: {expected_item_id}"
            ) from exc
        if record.item_id != expected_item_id:
            raise ArtifactIntegrityError("item feature record identity mismatch")
        return record


class SegmentProxyRecordLoader:
    def __init__(self, resolver: ResourceResolver) -> None:
        self._resolver = resolver

    def load(
        self,
        ref: ResourceRef,
        *,
        expected_item_id: str,
        expected_segment_id: str,
    ) -> SegmentProxyRecord:
        try:
            record = decode_canonical_json(
                self._resolver.read_verified_bytes(ref),
                SegmentProxyRecord,
                logical_name=f"segment proxy {expected_item_id}/{expected_segment_id}",
            )
        except DatasetValidationError as exc:
            raise ArtifactIntegrityError(
                f"invalid segment proxy record: {expected_item_id}/{expected_segment_id}"
            ) from exc
        if (record.item_id, record.segment_id) != (
            expected_item_id,
            expected_segment_id,
        ):
            raise ArtifactIntegrityError("segment proxy record identity mismatch")
        return record
