"""Pure deterministic Evidence and Observation state transitions."""

from pave_rec.domain import (
    ComponentDescriptor,
    Evidence,
    EvidenceState,
    ItemEvidenceState,
    ItemObservationState,
    ObservationState,
    ObservationStatus,
    PerceptionResult,
    SegmentObservationState,
)
from pave_rec.errors import ContractError


class MockEvidenceUpdater:
    descriptor = ComponentDescriptor(
        role="evidence_updater", implementation="MockEvidenceUpdater", version="mock-v1"
    )

    def update(self, state: EvidenceState, evidence: Evidence) -> EvidenceState:
        if any(
            existing.evidence_id == evidence.evidence_id
            for item in state.items
            for existing in item.evidence
        ):
            raise ContractError(f"duplicate evidence_id: {evidence.evidence_id}")
        found = False
        items: list[ItemEvidenceState] = []
        for item in state.items:
            if item.item_id != evidence.item_id:
                items.append(item)
                continue
            found = True
            updated_evidence = (*item.evidence, evidence)
            items.append(
                ItemEvidenceState(
                    item_id=item.item_id,
                    evidence=updated_evidence,
                    aggregated_attributes={
                        "mock_evidence_ids": [entry.evidence_id for entry in updated_evidence]
                    },
                    evidence_embedding_ref=item.evidence_embedding_ref,
                )
            )
        if not found:
            raise ContractError(f"evidence references unknown item: {evidence.item_id}")
        return EvidenceState(items=tuple(items))


class MockObservationUpdater:
    descriptor = ComponentDescriptor(
        role="observation_updater",
        implementation="MockObservationUpdater",
        version="mock-v1",
    )

    def update(
        self,
        state: ObservationState,
        result: PerceptionResult,
        attempt_step: int,
    ) -> ObservationState:
        if attempt_step < 1:
            raise ContractError("attempt_step must be positive")
        found = False
        items: list[ItemObservationState] = []
        for item in state.items:
            observations: list[SegmentObservationState] = []
            for observation in item.segment_observations:
                if (observation.item_id, observation.segment_id) != (
                    result.item_id,
                    result.segment_id,
                ):
                    observations.append(observation)
                    continue
                found = True
                if observation.status is not ObservationStatus.UNOBSERVED:
                    raise ContractError("an observed segment cannot be attempted again")
                evidence_ids = ()
                failure_reason = result.failure_reason
                if result.status is ObservationStatus.SUCCEEDED:
                    if result.evidence is None:
                        raise ContractError("successful perception result is missing Evidence")
                    evidence_ids = (result.evidence.evidence_id,)
                    failure_reason = None
                observations.append(
                    SegmentObservationState(
                        item_id=result.item_id,
                        segment_id=result.segment_id,
                        status=result.status,
                        attempt_count=observation.attempt_count + 1,
                        evidence_ids=evidence_ids,
                        failure_reason=failure_reason,
                        last_attempt_step=attempt_step,
                    )
                )
            items.append(
                ItemObservationState(
                    item_id=item.item_id,
                    segment_observations=tuple(observations),
                )
            )
        if not found:
            identity = f"{result.item_id}/{result.segment_id}"
            raise ContractError(f"perception result references unknown segment: {identity}")
        return ObservationState(items=tuple(items))
