"""Initial-ranker component protocol."""

from typing import Protocol

from pave_rec.domain import ComponentDescriptor, InitialRankingOutput


class InitialRanker(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def score(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
    ) -> InitialRankingOutput: ...
