"""Immutable recommendation-state snapshots and their cross-object invariants."""

from pydantic import ValidationInfo, field_validator, model_validator

from .base import FrozenModel, JsonObject, require_finite, require_non_empty, require_unique
from .enums import ObservationStatus
from .evidence import ItemEvidenceState, SegmentObservationState
from .memory import UserMemoryView
from .refs import ResourceRef
from .segments import SegmentProxyRef


class RankingUncertainty(FrozenModel):
    top1_top2_margin: float | None = None

    @field_validator("top1_top2_margin")
    @classmethod
    def _validate_margin(cls, value: float | None) -> float | None:
        if value is not None:
            require_finite(value, "top1_top2_margin")
            if value < 0:
                raise ValueError("top1_top2_margin must be non-negative")
        return value


class CandidateState(FrozenModel):
    item_id: str
    initial_score: float
    current_score: float
    initial_rank: int
    current_rank: int
    segment_observations: tuple[SegmentObservationState, ...]
    unobserved_segment_ids: tuple[str, ...]
    evidence: ItemEvidenceState
    item_feature_ref: ResourceRef | None = None
    segment_proxy_refs: tuple[SegmentProxyRef, ...]

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")

    @field_validator("initial_score", "current_score")
    @classmethod
    def _validate_scores(cls, value: float, info: ValidationInfo) -> float:
        return require_finite(value, info.field_name)

    @field_validator("initial_rank", "current_rank")
    @classmethod
    def _validate_ranks(cls, value: int, info: ValidationInfo) -> int:
        if value < 1:
            raise ValueError(f"{info.field_name} must start at 1")
        return value

    @field_validator("unobserved_segment_ids")
    @classmethod
    def _validate_unobserved_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for segment_id in value:
            require_non_empty(segment_id, "unobserved segment ID")
        return require_unique(value, "unobserved segment IDs")

    @model_validator(mode="after")
    def _validate_candidate_snapshot(self) -> "CandidateState":
        if self.evidence.item_id != self.item_id:
            raise ValueError("candidate evidence item_id mismatch")
        observations = {obs.segment_id: obs for obs in self.segment_observations}
        if len(observations) != len(self.segment_observations):
            raise ValueError("candidate segment observations contain duplicates")
        proxies = {ref.segment_id: ref for ref in self.segment_proxy_refs}
        if len(proxies) != len(self.segment_proxy_refs):
            raise ValueError("candidate segment proxy refs contain duplicates")
        for observation in self.segment_observations:
            if observation.item_id != self.item_id:
                raise ValueError("candidate observation item_id mismatch")
        for proxy in self.segment_proxy_refs:
            if proxy.item_id != self.item_id:
                raise ValueError("candidate proxy item_id mismatch")
        if tuple(observations) != tuple(proxies):
            raise ValueError(
                "candidate observations and proxy refs must have identical order/coverage"
            )
        derived_unobserved = tuple(
            obs.segment_id
            for obs in self.segment_observations
            if obs.status is ObservationStatus.UNOBSERVED
        )
        if self.unobserved_segment_ids != derived_unobserved:
            raise ValueError("unobserved_segment_ids must be derived from observation state")
        evidence_by_id = {e.evidence_id: e for e in self.evidence.evidence}
        for observation in self.segment_observations:
            for evidence_id in observation.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None or evidence.segment_id != observation.segment_id:
                    raise ValueError("observation references inconsistent evidence")
        referenced = {
            evidence_id
            for observation in self.segment_observations
            for evidence_id in observation.evidence_ids
        }
        if referenced != set(evidence_by_id):
            raise ValueError("candidate evidence must be referenced by observations")
        return self


class RecommendationState(FrozenModel):
    schema_version: str
    run_id: str
    user_id: str
    user_memory: UserMemoryView
    candidates: tuple[CandidateState, ...]
    max_perception_actions: int
    remaining_perception_actions: int
    step: int
    ranking_uncertainty: RankingUncertainty
    metadata: JsonObject

    @field_validator("schema_version", "run_id", "user_id")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_state(self) -> "RecommendationState":
        if not self.candidates:
            raise ValueError("recommendation state must contain candidates")
        require_unique(tuple(c.item_id for c in self.candidates), "state candidate IDs")
        initial_ranks = sorted(candidate.initial_rank for candidate in self.candidates)
        current_ranks = tuple(candidate.current_rank for candidate in self.candidates)
        expected = list(range(1, len(self.candidates) + 1))
        if initial_ranks != expected:
            raise ValueError("initial ranks must be contiguous and unique")
        if current_ranks != tuple(expected):
            raise ValueError("candidates must be ordered by contiguous current rank")
        if (
            self.max_perception_actions < 0
            or self.remaining_perception_actions < 0
            or self.step < 0
        ):
            raise ValueError("budget and step values must be non-negative")
        if self.remaining_perception_actions != self.max_perception_actions - self.step:
            raise ValueError(
                "remaining_perception_actions must equal max_perception_actions - step"
            )
        expected_margin = None
        if len(self.candidates) >= 2:
            expected_margin = round(
                self.candidates[0].current_score - self.candidates[1].current_score, 12
            )
        if self.ranking_uncertainty.top1_top2_margin != expected_margin:
            raise ValueError("top1_top2_margin must match the top two current scores")
        return self
