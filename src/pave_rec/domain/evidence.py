"""Evidence and observation runtime-state schemas."""

from pydantic import ValidationInfo, field_validator, model_validator

from .base import (
    FrozenModel,
    JsonObject,
    require_non_empty,
    require_optional_non_empty,
    require_range,
    require_unique,
)
from .enums import ObservationStatus
from .refs import ResourceRef


class Evidence(FrozenModel):
    evidence_id: str
    item_id: str
    segment_id: str
    attributes: JsonObject
    text_summary: str | None = None
    confidence: float | None = None
    source: str
    raw_output_ref: ResourceRef | None = None
    embedding_ref: ResourceRef | None = None
    metadata: JsonObject

    @field_validator("evidence_id", "item_id", "segment_id", "source")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("text_summary")
    @classmethod
    def _validate_summary(cls, value: str | None) -> str | None:
        return require_optional_non_empty(value, "text_summary")

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float | None) -> float | None:
        if value is not None:
            return require_range(value, "confidence", 0.0, 1.0)
        return value


class SegmentObservationState(FrozenModel):
    item_id: str
    segment_id: str
    status: ObservationStatus
    attempt_count: int
    evidence_ids: tuple[str, ...]
    failure_reason: str | None = None
    last_attempt_step: int | None = None

    @field_validator("item_id", "segment_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("evidence_ids")
    @classmethod
    def _validate_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for evidence_id in value:
            require_non_empty(evidence_id, "evidence_id")
        return require_unique(value, "evidence_ids")

    @model_validator(mode="after")
    def _validate_status_fields(self) -> "SegmentObservationState":
        if self.attempt_count < 0:
            raise ValueError("attempt_count must be non-negative")
        if self.status is ObservationStatus.UNOBSERVED:
            if self.attempt_count != 0 or self.evidence_ids:
                raise ValueError("unobserved segments cannot have attempts or evidence")
            if self.failure_reason is not None or self.last_attempt_step is not None:
                raise ValueError("unobserved segments cannot have failure/attempt metadata")
        else:
            if self.attempt_count < 1:
                raise ValueError("observed segments must have at least one attempt")
            if self.last_attempt_step is None or self.last_attempt_step < 1:
                raise ValueError("observed segments require a positive last_attempt_step")
        if self.status is ObservationStatus.SUCCEEDED:
            if not self.evidence_ids or self.failure_reason is not None:
                raise ValueError("successful observations require evidence and no failure reason")
        if self.status is ObservationStatus.FAILED:
            if self.evidence_ids or not self.failure_reason or not self.failure_reason.strip():
                raise ValueError("failed observations require a reason and no evidence")
        return self


class ItemEvidenceState(FrozenModel):
    item_id: str
    evidence: tuple[Evidence, ...]
    aggregated_attributes: JsonObject
    evidence_embedding_ref: ResourceRef | None = None

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")

    @model_validator(mode="after")
    def _validate_evidence(self) -> "ItemEvidenceState":
        ids: list[str] = []
        for evidence in self.evidence:
            if evidence.item_id != self.item_id:
                raise ValueError("evidence item_id must match ItemEvidenceState.item_id")
            ids.append(evidence.evidence_id)
        require_unique(tuple(ids), "evidence IDs")
        return self


class EvidenceState(FrozenModel):
    items: tuple[ItemEvidenceState, ...]

    @model_validator(mode="after")
    def _validate_items(self) -> "EvidenceState":
        require_unique(tuple(item.item_id for item in self.items), "EvidenceState item IDs")
        all_ids = tuple(e.evidence_id for item in self.items for e in item.evidence)
        require_unique(all_ids, "run evidence IDs")
        return self


class ItemObservationState(FrozenModel):
    item_id: str
    segment_observations: tuple[SegmentObservationState, ...]

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")

    @model_validator(mode="after")
    def _validate_observations(self) -> "ItemObservationState":
        segment_ids: list[str] = []
        for observation in self.segment_observations:
            if observation.item_id != self.item_id:
                raise ValueError("observation item_id must match ItemObservationState.item_id")
            segment_ids.append(observation.segment_id)
        require_unique(tuple(segment_ids), "segment IDs within an item")
        return self


class ObservationState(FrozenModel):
    items: tuple[ItemObservationState, ...]

    @model_validator(mode="after")
    def _validate_items(self) -> "ObservationState":
        require_unique(tuple(item.item_id for item in self.items), "ObservationState item IDs")
        return self
