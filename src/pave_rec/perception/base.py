"""Selected-segment perception protocol."""

from typing import Protocol

from pave_rec.domain import ComponentDescriptor, PerceptionRequest, PerceptionResult


class SegmentPerceiver(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def observe(self, request: PerceptionRequest) -> PerceptionResult: ...
