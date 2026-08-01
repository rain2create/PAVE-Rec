"""Fixture-backed initial ranker for Phase 1."""

from pave_rec.domain import ComponentDescriptor, InitialRankingOutput
from pave_rec.errors import ContractError
from pave_rec.fixture import MockFixture


class MockInitialRanker:
    descriptor = ComponentDescriptor(
        role="initial_ranker", implementation="MockInitialRanker", version="mock-v1"
    )

    def __init__(self, fixture: MockFixture) -> None:
        self._fixture = fixture

    def score(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
    ) -> InitialRankingOutput:
        expected = self._fixture.input
        if (
            user_id != expected.user_id
            or sequence != expected.history
            or candidate_ids != expected.candidate_ids
        ):
            raise ContractError("unknown MockInitialRanker fixture key")
        return self._fixture.initial_ranking
