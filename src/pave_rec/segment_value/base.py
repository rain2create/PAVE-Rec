"""Segment-value component protocol."""

from typing import Protocol

from pave_rec.domain import ComponentDescriptor, SegmentValue, SegmentValueInput


class SegmentValueModel(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def predict(self, request: SegmentValueInput) -> tuple[SegmentValue, ...]: ...
