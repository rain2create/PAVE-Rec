"""Full train-vocabulary next-item evaluation and deterministic MostPop baseline."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

from pave_rec.domain import (
    ComponentDescriptor,
    InitialRankedCandidate,
    InitialRankingOutput,
)
from pave_rec.errors import ArtifactIntegrityError, ContractError
from pave_rec.phase3.derived import DerivedDataset, DerivedTarget

from .models import MetricAggregate, RankingEvaluationAggregate, TargetRankingOutcome

TargetRankingRequest = tuple[str, tuple[str, ...], tuple[str, ...], str]


class CandidateRanker(Protocol):
    def score(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
    ) -> InitialRankingOutput: ...

    def rank_target(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
        target_item_id: str,
    ) -> tuple[int, tuple[str, ...]]: ...

    def rank_targets(
        self,
        requests: tuple[TargetRankingRequest, ...],
        *,
        user_batch_size: int,
    ) -> tuple[tuple[int, tuple[str, ...]], ...]: ...


class MostPopInitialRanker:
    descriptor = ComponentDescriptor(
        role="initial_ranker", implementation="MostPopInitialRanker", version="mostpop-v1"
    )

    def __init__(self, counts: dict[str, int]) -> None:
        if not counts or any(not item_id or count < 0 for item_id, count in counts.items()):
            raise ValueError("MostPop requires non-negative train-only item counts")
        self._counts = dict(counts)
        self._ordered_item_ids = tuple(
            sorted(self._counts, key=lambda item_id: (-self._counts[item_id], item_id))
        )

    def _ordered_candidates(
        self,
        user_id: str,
        candidate_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        candidates = self._candidate_set(user_id, candidate_ids)
        return tuple(item_id for item_id in self._ordered_item_ids if item_id in candidates)

    def _candidate_set(self, user_id: str, candidate_ids: tuple[str, ...]) -> set[str]:
        if not user_id or not candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
            raise ContractError("MostPop requires a user and unique non-empty candidates")
        if any(item_id not in self._counts for item_id in candidate_ids):
            raise ContractError("MostPop candidate is outside the train vocabulary")
        return set(candidate_ids)

    def score(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
    ) -> InitialRankingOutput:
        ordered = self._ordered_candidates(user_id, candidate_ids)
        return InitialRankingOutput(
            candidates=tuple(
                InitialRankedCandidate(
                    item_id=item_id,
                    score=float(self._counts[item_id]),
                    rank=rank,
                )
                for rank, item_id in enumerate(ordered, start=1)
            ),
            user_sequence_feature_ref=None,
            metadata={
                "ranker_type": "mostpop",
                "ranker_version": "mostpop-v1",
                "count_source": "train-only-positive-frequency",
            },
        )

    def rank_target(
        self,
        user_id: str,
        sequence: tuple[str, ...],
        candidate_ids: tuple[str, ...],
        target_item_id: str,
    ) -> tuple[int, tuple[str, ...]]:
        del sequence
        candidates = self._candidate_set(user_id, candidate_ids)
        if target_item_id not in candidates:
            raise ContractError("MostPop target is outside the candidate set")
        rank = 0
        target_rank = None
        top_100 = []
        for item_id in self._ordered_item_ids:
            if item_id not in candidates:
                continue
            rank += 1
            if len(top_100) < 100:
                top_100.append(item_id)
            if item_id == target_item_id:
                target_rank = rank
            if target_rank is not None and len(top_100) == min(100, len(candidates)):
                break
        if target_rank is None:  # pragma: no cover - closed by exact coverage above
            raise ContractError("MostPop target rank could not be resolved")
        return target_rank, tuple(top_100)

    def rank_targets(
        self,
        requests: tuple[TargetRankingRequest, ...],
        *,
        user_batch_size: int,
    ) -> tuple[tuple[int, tuple[str, ...]], ...]:
        if user_batch_size <= 0:
            raise ContractError("MostPop evaluation batch size must be positive")
        return tuple(self.rank_target(*request) for request in requests)


def build_mostpop_ranker(dataset: DerivedDataset) -> MostPopInitialRanker:
    counts = {entry.item_id: 0 for entry in dataset.vocabulary.entries}
    for split in dataset.user_splits:
        for event in split.train_events:
            try:
                counts[event.item_id] += 1
            except KeyError as exc:
                raise ArtifactIntegrityError("train event is outside its vocabulary") from exc
    return MostPopInitialRanker(counts)


@dataclass(frozen=True)
class RankingEvaluation:
    aggregate: RankingEvaluationAggregate
    outcomes: tuple[TargetRankingOutcome, ...]


def _targets(dataset: DerivedDataset, split: Literal["validation", "test"]):
    return tuple(
        user_split.validation_target if split == "validation" else user_split.test_target
        for user_split in dataset.user_splits
    )


def _candidate_ids(dataset: DerivedDataset, target: DerivedTarget) -> tuple[str, ...]:
    seen = {event.item_id for event in target.history}
    return tuple(
        entry.item_id
        for entry in dataset.vocabulary.entries
        if entry.item_id not in seen or entry.item_id == target.target.item_id
    )


def _metric(value: float, denominator: int) -> MetricAggregate:
    return MetricAggregate(numerator=value, denominator=denominator, mean=value / denominator)


def evaluate_full_catalog(
    dataset: DerivedDataset,
    *,
    split: Literal["validation", "test"],
    ranker: CandidateRanker,
    user_batch_size: int = 128,
) -> RankingEvaluation:
    targets = _targets(dataset, split)
    if not targets:
        raise ArtifactIntegrityError("evaluation target subset is empty")
    vocabulary = {entry.item_id for entry in dataset.vocabulary.entries}
    if user_batch_size <= 0:
        raise ContractError("evaluation user_batch_size must be positive")
    outcomes = []
    warm_ranks = []
    for start in range(0, len(targets), user_batch_size):
        target_batch = targets[start : start + user_batch_size]
        batch_outcomes: list[TargetRankingOutcome | None] = [None] * len(target_batch)
        warm_requests = []
        warm_positions = []
        for position, target in enumerate(target_batch):
            if target.target.item_id not in vocabulary:
                batch_outcomes[position] = TargetRankingOutcome(
                    schema_version="p3-target-ranking-outcome-v1",
                    split=split,
                    sample_id=target.sample_id,
                    user_id=target.user_id,
                    target_item_id=target.target.item_id,
                    cutoff_identity=target.cutoff_identity,
                    warm_target=False,
                    candidate_count=0,
                    target_rank=None,
                    miss_reason="cold_target",
                    top_100_item_ids=(),
                )
                continue
            candidates = _candidate_ids(dataset, target)
            warm_positions.append(position)
            warm_requests.append(
                (
                    target.user_id,
                    tuple(event.item_id for event in target.history),
                    candidates,
                    target.target.item_id,
                )
            )
        ranked = ranker.rank_targets(
            tuple(warm_requests),
            user_batch_size=user_batch_size,
        )
        if len(ranked) != len(warm_requests):
            raise ArtifactIntegrityError("ranker returned the wrong batch result count")
        for position, request, (rank, top_100) in zip(
            warm_positions, warm_requests, ranked, strict=True
        ):
            target = target_batch[position]
            candidates = request[2]
            candidate_set = set(candidates)
            if rank < 1 or rank > len(candidates):
                raise ArtifactIntegrityError("ranker returned an invalid exact target rank")
            if len(top_100) != min(100, len(candidates)) or len(top_100) != len(set(top_100)):
                raise ArtifactIntegrityError("ranker returned invalid Top-100 coverage")
            if any(item_id not in candidate_set for item_id in top_100):
                raise ArtifactIntegrityError("ranker Top-100 contains a foreign candidate")
            if (rank <= 100) != (target.target.item_id in top_100):
                raise ArtifactIntegrityError("ranker target rank disagrees with Top-100 membership")
            warm_ranks.append(rank)
            batch_outcomes[position] = TargetRankingOutcome(
                schema_version="p3-target-ranking-outcome-v1",
                split=split,
                sample_id=target.sample_id,
                user_id=target.user_id,
                target_item_id=target.target.item_id,
                cutoff_identity=target.cutoff_identity,
                warm_target=True,
                candidate_count=len(candidates),
                target_rank=rank,
                miss_reason=None,
                top_100_item_ids=top_100,
            )
        if any(outcome is None for outcome in batch_outcomes):
            raise ArtifactIntegrityError("evaluation batch left an unresolved target")
        outcomes.extend(outcome for outcome in batch_outcomes if outcome is not None)
    warm_count = len(warm_ranks)
    all_count = len(targets)
    if warm_count == 0:
        raise ArtifactIntegrityError("warm evaluation subset is empty")
    sums = {
        "ndcg_at_10": math.fsum(
            1.0 / math.log2(rank + 1) if rank <= 10 else 0.0 for rank in warm_ranks
        ),
        "hr_at_10": math.fsum(1.0 if rank <= 10 else 0.0 for rank in warm_ranks),
        "ndcg_at_20": math.fsum(
            1.0 / math.log2(rank + 1) if rank <= 20 else 0.0 for rank in warm_ranks
        ),
        "hr_at_20": math.fsum(1.0 if rank <= 20 else 0.0 for rank in warm_ranks),
        "mrr_at_10": math.fsum(1.0 / rank if rank <= 10 else 0.0 for rank in warm_ranks),
        "recall_at_100": math.fsum(1.0 if rank <= 100 else 0.0 for rank in warm_ranks),
    }
    aggregate = RankingEvaluationAggregate(
        schema_version="p3-ranking-evaluation-aggregate-v1",
        split=split,
        all_target_count=all_count,
        warm_target_count=warm_count,
        cold_target_count=all_count - warm_count,
        all_target_retrieval_coverage=_metric(float(warm_count), all_count),
        warm_metrics={key: _metric(value, warm_count) for key, value in sums.items()},
    )
    return RankingEvaluation(aggregate=aggregate, outcomes=tuple(outcomes))
