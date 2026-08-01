"""Deterministic mock perceiver with explicit test fault injection."""

from collections.abc import Mapping, Set

from pave_rec.domain import ComponentDescriptor, PerceptionRequest, PerceptionResult
from pave_rec.errors import ComponentExecutionError, ContractError

SegmentIdentity = tuple[str, str]


class MockPerceiver:
    descriptor = ComponentDescriptor(
        role="perceiver", implementation="MockPerceiver", version="mock-v1"
    )

    def __init__(
        self,
        results: tuple[PerceptionResult, ...],
        *,
        result_overrides: Mapping[SegmentIdentity, PerceptionResult] | None = None,
        exception_identities: Set[SegmentIdentity] | None = None,
    ) -> None:
        self._results = {(entry.item_id, entry.segment_id): entry for entry in results}
        self._results.update(dict(result_overrides or {}))
        self._exception_identities = frozenset(exception_identities or ())
        self.call_count = 0

    def observe(self, request: PerceptionRequest) -> PerceptionResult:
        identity = (request.segment.item_id, request.segment.segment_id)
        self.call_count += 1
        if identity in self._exception_identities:
            raise ComponentExecutionError(
                f"configured MockPerceiver exception for {identity[0]}/{identity[1]}"
            )
        try:
            return self._results[identity]
        except KeyError as exc:
            raise ContractError(
                f"unknown perception fixture key: {identity[0]}/{identity[1]}"
            ) from exc
