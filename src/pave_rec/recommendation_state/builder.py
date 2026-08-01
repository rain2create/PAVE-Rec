"""Deterministic construction of complete immutable recommendation snapshots."""

from pydantic import ValidationError

from pave_rec.domain import (
    CandidateState,
    ComponentDescriptor,
    EvidenceState,
    ItemEvidenceState,
    ItemObservationState,
    ItemSegmentCatalog,
    ObservationState,
    ObservationStatus,
    RankingUncertainty,
    RecommendationState,
    RecommendationStateBuildRequest,
    SegmentObservationState,
)
from pave_rec.errors import ContractError


def empty_evidence_state(candidate_ids: tuple[str, ...]) -> EvidenceState:
    return EvidenceState(
        items=tuple(
            ItemEvidenceState(
                item_id=item_id,
                evidence=(),
                aggregated_attributes={},
                evidence_embedding_ref=None,
            )
            for item_id in candidate_ids
        )
    )


def empty_observation_state(
    candidate_ids: tuple[str, ...],
    catalog: tuple[ItemSegmentCatalog, ...],
) -> ObservationState:
    catalogs = {entry.item_id: entry for entry in catalog}
    return ObservationState(
        items=tuple(
            ItemObservationState(
                item_id=item_id,
                segment_observations=tuple(
                    SegmentObservationState(
                        item_id=item_id,
                        segment_id=segment.segment_id,
                        status=ObservationStatus.UNOBSERVED,
                        attempt_count=0,
                        evidence_ids=(),
                        failure_reason=None,
                        last_attempt_step=None,
                    )
                    for segment in catalogs[item_id].segments
                ),
            )
            for item_id in candidate_ids
        )
    )


def _index_unique(entries: tuple[object, ...], *, field: str, label: str) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for entry in entries:
        identity = getattr(entry, field)
        if identity in indexed:
            raise ContractError(f"duplicate {label}: {identity}")
        indexed[identity] = entry
    return indexed


class DefaultRecommendationStateBuilder:
    descriptor = ComponentDescriptor(
        role="state_builder",
        implementation="DefaultRecommendationStateBuilder",
        version="phase1-v1",
    )

    def build(self, request: RecommendationStateBuildRequest) -> RecommendationState:
        initial = _index_unique(
            request.initial_ranking.candidates, field="item_id", label="initial candidate"
        )
        scores = _index_unique(request.current_scores, field="item_id", label="current score")
        features = _index_unique(request.item_feature_refs, field="item_id", label="item feature")
        catalogs = _index_unique(request.segment_catalog, field="item_id", label="catalog")
        evidence = _index_unique(
            request.evidence_state.items, field="item_id", label="evidence item"
        )
        observations = _index_unique(
            request.observation_state.items, field="item_id", label="observation item"
        )
        candidate_ids = tuple(candidate.item_id for candidate in request.initial_ranking.candidates)
        expected = set(candidate_ids)
        for label, indexed in (
            ("current scores", scores),
            ("item features", features),
            ("segment catalog", catalogs),
            ("evidence state", evidence),
            ("observation state", observations),
        ):
            if set(indexed) != expected:
                raise ContractError(f"{label} must cover exactly the initial candidates")

        ordered_ids = sorted(candidate_ids, key=lambda item_id: (-scores[item_id].score, item_id))
        candidates: list[CandidateState] = []
        for current_rank, item_id in enumerate(ordered_ids, start=1):
            initial_candidate = initial[item_id]
            catalog = catalogs[item_id]
            item_observations = observations[item_id]
            try:
                candidates.append(
                    CandidateState(
                        item_id=item_id,
                        initial_score=initial_candidate.score,
                        current_score=scores[item_id].score,
                        initial_rank=initial_candidate.rank,
                        current_rank=current_rank,
                        segment_observations=item_observations.segment_observations,
                        unobserved_segment_ids=tuple(
                            observation.segment_id
                            for observation in item_observations.segment_observations
                            if observation.status is ObservationStatus.UNOBSERVED
                        ),
                        evidence=evidence[item_id],
                        item_feature_ref=features[item_id].feature_ref,
                        segment_proxy_refs=catalog.segment_proxy_refs,
                    )
                )
            except ValidationError as exc:
                raise ContractError(f"invalid candidate state for {item_id}: {exc}") from exc

        margin = None
        if len(candidates) >= 2:
            margin = round(candidates[0].current_score - candidates[1].current_score, 12)
        try:
            return RecommendationState(
                schema_version=request.schema_version,
                run_id=request.run_id,
                user_id=request.user_id,
                user_memory=request.user_memory,
                candidates=tuple(candidates),
                max_perception_actions=request.max_perception_actions,
                remaining_perception_actions=request.remaining_perception_actions,
                step=request.step,
                ranking_uncertainty=RankingUncertainty(top1_top2_margin=margin),
                metadata=request.metadata,
            )
        except ValidationError as exc:
            raise ContractError(f"invalid recommendation state: {exc}") from exc
