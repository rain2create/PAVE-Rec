"""Persisted step-trace and final-result schemas."""

from pydantic import ValidationInfo, field_validator, model_validator

from .base import FrozenModel, JsonObject, require_non_empty, require_unique
from .decisions import InformationNeed, SegmentValue, StopDecision
from .enums import StopReason
from .interface_types import ComponentDescriptor, PerceptionResult
from .segments import SegmentMeta
from .state import RecommendationState


class AgentStepTrace(FrozenModel):
    schema_version: str
    run_id: str
    decision_index: int
    state_before: RecommendationState | None = None
    information_need: InformationNeed | None = None
    segment_values: tuple[SegmentValue, ...] | None = None
    selected_segment: SegmentMeta | None = None
    selected_segment_value: SegmentValue | None = None
    perception_result: PerceptionResult | None = None
    state_after: RecommendationState | None = None
    action_consumed: bool
    stop_decision: StopDecision | None = None
    metadata: JsonObject

    @field_validator("schema_version", "run_id")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("decision_index")
    @classmethod
    def _validate_index(cls, value: int) -> int:
        if value < 0:
            raise ValueError("decision_index must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_identities(self) -> "AgentStepTrace":
        for state in (self.state_before, self.state_after):
            if state is not None and state.run_id != self.run_id:
                raise ValueError("trace and state run IDs must match")
        if self.selected_segment is not None and self.selected_segment_value is not None:
            segment_identity = (self.selected_segment.item_id, self.selected_segment.segment_id)
            value_identity = (
                self.selected_segment_value.item_id,
                self.selected_segment_value.segment_id,
            )
            if segment_identity != value_identity:
                raise ValueError("selected segment/value identities must match")
        if self.perception_result is not None and self.selected_segment is not None:
            result_identity = (self.perception_result.item_id, self.perception_result.segment_id)
            segment_identity = (self.selected_segment.item_id, self.selected_segment.segment_id)
            if result_identity != segment_identity:
                raise ValueError("perception result must match the selected segment")
        return self


class AgentRunResult(FrozenModel):
    schema_version: str
    run_id: str
    succeeded: bool
    final_state: RecommendationState | None = None
    stop_decision: StopDecision
    attempted_perception_actions: int
    trace_record_count: int
    seed: int
    data_version: str
    component_descriptors: tuple[ComponentDescriptor, ...]
    git_commit: str | None = None
    git_dirty: bool | None = None
    metadata: JsonObject

    @field_validator("schema_version", "run_id", "data_version")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("git_commit")
    @classmethod
    def _validate_commit(cls, value: str | None) -> str | None:
        if value is not None:
            return require_non_empty(value, "git_commit")
        return value

    @model_validator(mode="after")
    def _validate_result(self) -> "AgentRunResult":
        if self.attempted_perception_actions < 0 or self.seed < 0:
            raise ValueError("attempted actions and seed must be non-negative")
        if self.trace_record_count < 1:
            raise ValueError("a persisted run result requires at least one trace record")
        if not self.stop_decision.stop:
            raise ValueError("run result requires a terminal stop decision")
        if self.succeeded:
            if self.final_state is None:
                raise ValueError("successful runs require a final state")
            if self.stop_decision.reason in {
                StopReason.COMPONENT_FAILURE,
                StopReason.SAFETY_LIMIT_REACHED,
            }:
                raise ValueError("failure stop reasons cannot produce a successful result")
        elif self.stop_decision.reason not in {
            StopReason.COMPONENT_FAILURE,
            StopReason.SAFETY_LIMIT_REACHED,
        }:
            raise ValueError("failed results require component or safety failure")
        if self.final_state is not None and self.final_state.run_id != self.run_id:
            raise ValueError("result and final-state run IDs must match")
        roles = tuple(descriptor.role for descriptor in self.component_descriptors)
        require_unique(roles, "component descriptor roles")
        return self
