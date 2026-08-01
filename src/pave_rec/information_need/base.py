"""Information-need estimator protocol."""

from typing import Protocol

from pave_rec.domain import ComponentDescriptor, InformationNeed, RecommendationState


class InformationNeedEstimator(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def estimate(self, state: RecommendationState) -> InformationNeed: ...
