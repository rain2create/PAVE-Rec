"""Agent-owned stop-policy and trace-writer protocols."""

from typing import Protocol

from pave_rec.domain import (
    AgentRunResult,
    AgentStepTrace,
    ComponentDescriptor,
    RecommendationState,
    SegmentValue,
    StopDecision,
)


class StopPolicy(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def decide_pre_value(self, state: RecommendationState) -> StopDecision: ...

    def decide_post_value(
        self, state: RecommendationState, best_segment_value: SegmentValue
    ) -> StopDecision: ...


class TraceWriter(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def write_step(self, record: AgentStepTrace) -> None: ...

    def write_result(self, result: AgentRunResult) -> None: ...
