"""Fixture-backed Information Need lookup."""

from pave_rec.domain import ComponentDescriptor, InformationNeed, RecommendationState
from pave_rec.errors import ContractError
from pave_rec.fixture import MockFixture


class MockInformationNeedEstimator:
    descriptor = ComponentDescriptor(
        role="information_need",
        implementation="MockInformationNeedEstimator",
        version="mock-v1",
    )

    def __init__(self, fixture: MockFixture) -> None:
        self._fixture = fixture

    def estimate(self, state: RecommendationState) -> InformationNeed:
        if state.user_memory != self._fixture.user_memory:
            raise ContractError("unknown MockInformationNeedEstimator memory signature")
        return self._fixture.information_need
