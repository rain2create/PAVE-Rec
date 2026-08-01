"""Fixture-backed batched segment-value lookup."""

from pave_rec.domain import ComponentDescriptor, SegmentValue, SegmentValueInput
from pave_rec.errors import ContractError


class MockSegmentValueModel:
    descriptor = ComponentDescriptor(
        role="segment_value", implementation="MockSegmentValueModel", version="mock-v1"
    )

    def __init__(self, values: tuple[SegmentValue, ...]) -> None:
        self._values = {(entry.item_id, entry.segment_id): entry for entry in values}

    def predict(self, request: SegmentValueInput) -> tuple[SegmentValue, ...]:
        try:
            return tuple(
                self._values[(segment.item_id, segment.segment_id)]
                for segment in request.candidate_segments
            )
        except KeyError as exc:
            item_id, segment_id = exc.args[0]
            raise ContractError(
                f"unknown segment-value fixture key: {item_id}/{segment_id}"
            ) from exc
