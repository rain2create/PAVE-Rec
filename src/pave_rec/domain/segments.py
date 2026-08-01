"""Static media-segment and proxy-reference schemas."""

from pydantic import ValidationInfo, field_validator, model_validator

from .base import FrozenModel, JsonObject, require_non_empty
from .refs import ResourceRef


class SegmentMeta(FrozenModel):
    item_id: str
    segment_id: str
    start_ms: int
    end_ms: int
    media_ref: ResourceRef
    metadata: JsonObject

    @field_validator("item_id", "segment_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_interval(self) -> "SegmentMeta":
        if self.start_ms < 0:
            raise ValueError("start_ms must be non-negative")
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class SegmentProxyRef(FrozenModel):
    item_id: str
    segment_id: str
    feature_ref: ResourceRef
    metadata: JsonObject

    @field_validator("item_id", "segment_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)
