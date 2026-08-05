"""Fail-closed Phase 4/5 component guards for the Phase 3 zero-budget runtime."""

from __future__ import annotations

from pave_rec.domain import (
    CandidateScore,
    ComponentDescriptor,
    Evidence,
    EvidenceState,
    InformationNeed,
    ObservationState,
    PerceptionRequest,
    PerceptionResult,
    RecommendationState,
    ScoreUpdateRequest,
    SegmentValue,
    SegmentValueInput,
)
from pave_rec.errors import ComponentExecutionError

GUARD_VERSION = "phase3-zero-budget-v1"


def _unavailable(role: str) -> ComponentExecutionError:
    return ComponentExecutionError(f"{role} is unavailable in the Phase 3 zero-budget runtime")


class UnavailableInformationNeedEstimator:
    descriptor = ComponentDescriptor(
        role="information_need",
        implementation="UnavailableInformationNeedEstimator",
        version=GUARD_VERSION,
    )

    def estimate(self, state: RecommendationState) -> InformationNeed:
        del state
        raise _unavailable(self.descriptor.role)


class UnavailableSegmentValueModel:
    descriptor = ComponentDescriptor(
        role="segment_value",
        implementation="UnavailableSegmentValueModel",
        version=GUARD_VERSION,
    )

    def predict(self, request: SegmentValueInput) -> tuple[SegmentValue, ...]:
        del request
        raise _unavailable(self.descriptor.role)


class UnavailableSegmentPerceiver:
    descriptor = ComponentDescriptor(
        role="perceiver",
        implementation="UnavailableSegmentPerceiver",
        version=GUARD_VERSION,
    )

    def observe(self, request: PerceptionRequest) -> PerceptionResult:
        del request
        raise _unavailable(self.descriptor.role)


class UnavailableEvidenceUpdater:
    descriptor = ComponentDescriptor(
        role="evidence_updater",
        implementation="UnavailableEvidenceUpdater",
        version=GUARD_VERSION,
    )

    def update(self, state: EvidenceState, evidence: Evidence) -> EvidenceState:
        del state, evidence
        raise _unavailable(self.descriptor.role)


class UnavailableObservationUpdater:
    descriptor = ComponentDescriptor(
        role="observation_updater",
        implementation="UnavailableObservationUpdater",
        version=GUARD_VERSION,
    )

    def update(
        self,
        state: ObservationState,
        result: PerceptionResult,
        attempt_step: int,
    ) -> ObservationState:
        del state, result, attempt_step
        raise _unavailable(self.descriptor.role)


class UnavailableScoreUpdater:
    descriptor = ComponentDescriptor(
        role="score_updater",
        implementation="UnavailableScoreUpdater",
        version=GUARD_VERSION,
    )

    def update(self, request: ScoreUpdateRequest) -> tuple[CandidateScore, ...]:
        del request
        raise _unavailable(self.descriptor.role)
