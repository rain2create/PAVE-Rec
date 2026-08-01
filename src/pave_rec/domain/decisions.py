"""Information-need, segment-value, and stop-decision schemas."""

from pydantic import ValidationInfo, field_validator, model_validator

from .base import FrozenModel, JsonObject, require_finite, require_non_empty, require_unique
from .enums import StopReason
from .refs import ResourceRef
from .state import RecommendationState


class InformationNeed(FrozenModel):
    need_id: str
    concept: str
    description: str
    relevant_preference_atom_ids: tuple[str, ...]
    preference_importance: float | None = None
    evidence_gap: float | None = None
    ranking_relevance: float | None = None
    contrastiveness: float | None = None
    embedding_ref: ResourceRef | None = None
    metadata: JsonObject

    @field_validator("need_id", "concept", "description")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("relevant_preference_atom_ids")
    @classmethod
    def _validate_atom_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for atom_id in value:
            require_non_empty(atom_id, "preference atom ID")
        return require_unique(value, "relevant preference atom IDs")

    @field_validator(
        "preference_importance",
        "evidence_gap",
        "ranking_relevance",
        "contrastiveness",
    )
    @classmethod
    def _validate_optional_values(cls, value: float | None, info: ValidationInfo) -> float | None:
        if value is not None:
            return require_finite(value, info.field_name)
        return value


class CandidateSegmentRef(FrozenModel):
    item_id: str
    segment_id: str
    item_feature_ref: ResourceRef | None = None
    segment_proxy_ref: ResourceRef | None = None

    @field_validator("item_id", "segment_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)


class SegmentValueInput(FrozenModel):
    state: RecommendationState
    information_need: InformationNeed
    candidate_segments: tuple[CandidateSegmentRef, ...]

    @model_validator(mode="after")
    def _validate_segments(self) -> "SegmentValueInput":
        identities = tuple((ref.item_id, ref.segment_id) for ref in self.candidate_segments)
        require_unique(identities, "candidate segment identities")
        if identities != tuple(sorted(identities)):
            raise ValueError("candidate segments must be ordered by (item_id, segment_id)")
        return self


class SegmentValue(FrozenModel):
    item_id: str
    segment_id: str
    value: float
    metadata: JsonObject

    @field_validator("item_id", "segment_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: float) -> float:
        return require_finite(value, "value")


class StopDecision(FrozenModel):
    stop: bool
    reason: StopReason | None = None
    details: JsonObject

    @model_validator(mode="after")
    def _validate_stop(self) -> "StopDecision":
        if self.stop and self.reason is None:
            raise ValueError("a terminal stop decision requires a reason")
        if not self.stop and self.reason is not None:
            raise ValueError("a continue decision cannot include a reason")
        if not self.stop and self.details:
            raise ValueError("a continue decision must use empty details")
        expected_keys = {
            StopReason.BUDGET_EXHAUSTED: {
                "max_perception_actions",
                "remaining_perception_actions",
                "step",
            },
            StopReason.NO_UNOBSERVED_SEGMENTS: {"unobserved_segment_count"},
            StopReason.RANKING_SUFFICIENTLY_CERTAIN: {
                "ranking_margin_threshold",
                "top1_top2_margin",
            },
            StopReason.MAX_SEGMENT_VALUE_TOO_LOW: {
                "item_id",
                "segment_id",
                "max_segment_value",
                "min_segment_value",
            },
            StopReason.COMPONENT_FAILURE: {"component_role", "error_type", "message"},
            StopReason.SAFETY_LIMIT_REACHED: {
                "decision_loop_entries",
                "max_decision_loop_entries",
            },
        }
        if self.stop and set(self.details) != expected_keys[self.reason]:
            raise ValueError(f"details keys do not match stop reason {self.reason.value}")
        return self
