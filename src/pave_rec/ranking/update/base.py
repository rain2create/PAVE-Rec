"""Score-update component protocol."""

from typing import Protocol

from pave_rec.domain import CandidateScore, ComponentDescriptor, ScoreUpdateRequest


class ScoreUpdater(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def update(self, request: ScoreUpdateRequest) -> tuple[CandidateScore, ...]: ...
