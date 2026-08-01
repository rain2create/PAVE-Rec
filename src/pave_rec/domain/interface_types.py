"""Strict request/result objects used at component boundaries."""

from pydantic import ValidationInfo, field_validator, model_validator

from .base import FrozenModel, JsonObject, require_finite, require_non_empty, require_unique
from .decisions import InformationNeed
from .enums import ObservationStatus
from .evidence import Evidence, EvidenceState, ItemEvidenceState, ObservationState
from .memory import UserMemoryView
from .ranking import InitialRankingOutput
from .refs import ResourceRef
from .segments import SegmentMeta, SegmentProxyRef


class AgentRunRequest(FrozenModel):
    run_id: str
    user_id: str
    user_history: tuple[str, ...]
    candidate_ids: tuple[str, ...]

    @field_validator("run_id", "user_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("user_history", "candidate_ids")
    @classmethod
    def _validate_item_tuples(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        for item_id in value:
            require_non_empty(item_id, info.field_name)
        return value

    @model_validator(mode="after")
    def _validate_candidates(self) -> "AgentRunRequest":
        if not self.candidate_ids:
            raise ValueError("candidate_ids must not be empty")
        require_unique(self.candidate_ids, "candidate_ids")
        return self


class ComponentDescriptor(FrozenModel):
    role: str
    implementation: str
    version: str

    @field_validator("role", "implementation", "version")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)


class CandidateScore(FrozenModel):
    item_id: str
    score: float

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")

    @field_validator("score")
    @classmethod
    def _validate_score(cls, value: float) -> float:
        return require_finite(value, "score")


class ItemFeatureRef(FrozenModel):
    item_id: str
    feature_ref: ResourceRef | None = None

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")


class ItemSegmentCatalog(FrozenModel):
    item_id: str
    segments: tuple[SegmentMeta, ...]
    segment_proxy_refs: tuple[SegmentProxyRef, ...]

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")

    @model_validator(mode="after")
    def _validate_catalog(self) -> "ItemSegmentCatalog":
        segment_identities = tuple(
            (segment.item_id, segment.segment_id) for segment in self.segments
        )
        proxy_identities = tuple(
            (proxy.item_id, proxy.segment_id) for proxy in self.segment_proxy_refs
        )
        if any(item_id != self.item_id for item_id, _ in segment_identities + proxy_identities):
            raise ValueError("catalog entries must match catalog item_id")
        require_unique(segment_identities, "catalog segment identities")
        require_unique(proxy_identities, "catalog proxy identities")
        expected_segments = tuple(
            sorted(
                self.segments,
                key=lambda segment: (segment.start_ms, segment.end_ms, segment.segment_id),
            )
        )
        if self.segments != expected_segments:
            raise ValueError("catalog segments must use canonical time/identity order")
        if segment_identities != proxy_identities:
            raise ValueError("segment proxies must match segment coverage and order")
        return self


class RecommendationStateBuildRequest(FrozenModel):
    schema_version: str
    run_id: str
    user_id: str
    user_memory: UserMemoryView
    initial_ranking: InitialRankingOutput
    current_scores: tuple[CandidateScore, ...]
    item_feature_refs: tuple[ItemFeatureRef, ...]
    segment_catalog: tuple[ItemSegmentCatalog, ...]
    evidence_state: EvidenceState
    observation_state: ObservationState
    max_perception_actions: int
    remaining_perception_actions: int
    step: int
    metadata: JsonObject

    @field_validator("schema_version", "run_id", "user_id")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_counters(self) -> "RecommendationStateBuildRequest":
        if (
            self.max_perception_actions < 0
            or self.remaining_perception_actions < 0
            or self.step < 0
        ):
            raise ValueError("budget and step values must be non-negative")
        if self.remaining_perception_actions != self.max_perception_actions - self.step:
            raise ValueError("remaining actions must equal max actions minus step")
        return self


class PerceptionRequest(FrozenModel):
    segment: SegmentMeta
    information_need: InformationNeed
    user_memory: UserMemoryView
    current_item_evidence: ItemEvidenceState
    metadata: JsonObject

    @model_validator(mode="after")
    def _validate_item(self) -> "PerceptionRequest":
        if self.segment.item_id != self.current_item_evidence.item_id:
            raise ValueError("perception segment/evidence item identity mismatch")
        return self


class PerceptionResult(FrozenModel):
    item_id: str
    segment_id: str
    status: ObservationStatus
    evidence: Evidence | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    metadata: JsonObject

    @field_validator("item_id", "segment_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_result(self) -> "PerceptionResult":
        if self.status is ObservationStatus.UNOBSERVED:
            raise ValueError("unobserved is not a valid PerceptionResult status")
        if self.status is ObservationStatus.SUCCEEDED:
            if self.evidence is None:
                raise ValueError("successful perception requires Evidence")
            if (self.evidence.item_id, self.evidence.segment_id) != (
                self.item_id,
                self.segment_id,
            ):
                raise ValueError("PerceptionResult and Evidence identities must match")
            if self.failure_code is not None or self.failure_reason is not None:
                raise ValueError("successful perception cannot contain failure fields")
        else:
            if self.evidence is not None:
                raise ValueError("failed perception cannot contain Evidence")
            if not self.failure_code or not self.failure_code.strip():
                raise ValueError("failed perception requires failure_code")
            if not self.failure_reason or not self.failure_reason.strip():
                raise ValueError("failed perception requires failure_reason")
        return self


class ScoreUpdateRequest(FrozenModel):
    user_memory: UserMemoryView
    initial_ranking: InitialRankingOutput
    previous_scores: tuple[CandidateScore, ...]
    item_feature_refs: tuple[ItemFeatureRef, ...]
    evidence_state: EvidenceState
    metadata: JsonObject

    @model_validator(mode="after")
    def _validate_coverage(self) -> "ScoreUpdateRequest":
        candidate_ids = tuple(candidate.item_id for candidate in self.initial_ranking.candidates)
        for name, identities in (
            ("previous_scores", tuple(entry.item_id for entry in self.previous_scores)),
            ("item_feature_refs", tuple(entry.item_id for entry in self.item_feature_refs)),
            ("evidence_state", tuple(entry.item_id for entry in self.evidence_state.items)),
        ):
            if identities != candidate_ids:
                raise ValueError(f"{name} must match initial-ranking candidate order and coverage")
        return self
