"""Fixture-delta score updater that always preserves the initial prior."""

from pave_rec.domain import CandidateScore, ComponentDescriptor, ScoreUpdateRequest
from pave_rec.errors import ContractError
from pave_rec.fixture import EvidenceScoreDelta


class MockScoreUpdater:
    descriptor = ComponentDescriptor(
        role="score_updater", implementation="MockScoreUpdater", version="mock-v1"
    )

    def __init__(self, score_deltas: tuple[EvidenceScoreDelta, ...]) -> None:
        self._deltas = {
            row.evidence_id: {entry.item_id: entry.score for entry in row.deltas}
            for row in score_deltas
        }

    def update(self, request: ScoreUpdateRequest) -> tuple[CandidateScore, ...]:
        evidence_ids = tuple(
            evidence.evidence_id
            for item in request.evidence_state.items
            for evidence in item.evidence
        )
        unknown = set(evidence_ids).difference(self._deltas)
        if unknown:
            raise ContractError(f"unknown score-delta evidence ID: {sorted(unknown)[0]}")
        scores: list[CandidateScore] = []
        for candidate in request.initial_ranking.candidates:
            delta = sum(
                self._deltas[evidence_id][candidate.item_id] for evidence_id in evidence_ids
            )
            scores.append(
                CandidateScore(item_id=candidate.item_id, score=round(candidate.score + delta, 12))
            )
        return tuple(scores)
