"""The configurable Phase 1 threshold stop policy and hard safety guard."""

from math import isfinite

from pave_rec.domain import (
    ComponentDescriptor,
    RecommendationState,
    SegmentValue,
    StopDecision,
    StopReason,
)


def continue_decision() -> StopDecision:
    return StopDecision(stop=False, reason=None, details={})


class ThresholdStopPolicy:
    descriptor = ComponentDescriptor(
        role="stop_policy", implementation="ThresholdStopPolicy", version="phase1-v1"
    )

    def __init__(
        self,
        *,
        ranking_margin_threshold: float | None,
        min_segment_value: float | None,
    ) -> None:
        if ranking_margin_threshold is not None and (
            not isfinite(ranking_margin_threshold) or ranking_margin_threshold < 0
        ):
            raise ValueError("ranking_margin_threshold must be finite and non-negative")
        if min_segment_value is not None and not isfinite(min_segment_value):
            raise ValueError("min_segment_value must be finite")
        self._ranking_margin_threshold = ranking_margin_threshold
        self._min_segment_value = min_segment_value

    def decide_pre_value(self, state: RecommendationState) -> StopDecision:
        if state.remaining_perception_actions == 0:
            return StopDecision(
                stop=True,
                reason=StopReason.BUDGET_EXHAUSTED,
                details={
                    "max_perception_actions": state.max_perception_actions,
                    "remaining_perception_actions": state.remaining_perception_actions,
                    "step": state.step,
                },
            )
        unobserved_count = sum(
            len(candidate.unobserved_segment_ids) for candidate in state.candidates
        )
        if unobserved_count == 0:
            return StopDecision(
                stop=True,
                reason=StopReason.NO_UNOBSERVED_SEGMENTS,
                details={"unobserved_segment_count": 0},
            )
        margin = state.ranking_uncertainty.top1_top2_margin
        if (
            self._ranking_margin_threshold is not None
            and margin is not None
            and margin >= self._ranking_margin_threshold
        ):
            return StopDecision(
                stop=True,
                reason=StopReason.RANKING_SUFFICIENTLY_CERTAIN,
                details={
                    "ranking_margin_threshold": self._ranking_margin_threshold,
                    "top1_top2_margin": margin,
                },
            )
        return continue_decision()

    def decide_post_value(
        self,
        state: RecommendationState,
        best_segment_value: SegmentValue,
    ) -> StopDecision:
        del state
        if (
            self._min_segment_value is not None
            and best_segment_value.value < self._min_segment_value
        ):
            return StopDecision(
                stop=True,
                reason=StopReason.MAX_SEGMENT_VALUE_TOO_LOW,
                details={
                    "item_id": best_segment_value.item_id,
                    "segment_id": best_segment_value.segment_id,
                    "max_segment_value": best_segment_value.value,
                    "min_segment_value": self._min_segment_value,
                },
            )
        return continue_decision()


def safety_decision(
    *, decision_loop_entries: int, max_decision_loop_entries: int
) -> StopDecision | None:
    if decision_loop_entries <= max_decision_loop_entries:
        return None
    return StopDecision(
        stop=True,
        reason=StopReason.SAFETY_LIMIT_REACHED,
        details={
            "decision_loop_entries": decision_loop_entries,
            "max_decision_loop_entries": max_decision_loop_entries,
        },
    )
