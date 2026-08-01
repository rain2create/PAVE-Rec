"""State-builder and pure transition protocols."""

from typing import Protocol

from pave_rec.domain import (
    ComponentDescriptor,
    Evidence,
    EvidenceState,
    ObservationState,
    PerceptionResult,
    RecommendationState,
    RecommendationStateBuildRequest,
)


class RecommendationStateBuilder(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def build(self, request: RecommendationStateBuildRequest) -> RecommendationState: ...


class EvidenceUpdater(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def update(self, state: EvidenceState, evidence: Evidence) -> EvidenceState: ...


class ObservationUpdater(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def update(
        self,
        state: ObservationState,
        result: PerceptionResult,
        attempt_step: int,
    ) -> ObservationState: ...
