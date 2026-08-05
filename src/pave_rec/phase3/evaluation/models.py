"""Strict records for full-catalog Phase 3 ranking evaluation."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from pave_rec.domain.base import FrozenModel, require_finite, require_non_empty, require_unique


class TargetRankingOutcome(FrozenModel):
    schema_version: Literal["p3-target-ranking-outcome-v1"]
    split: Literal["validation", "test"]
    sample_id: str
    user_id: str
    target_item_id: str
    cutoff_identity: str
    warm_target: bool
    candidate_count: int
    target_rank: int | None
    miss_reason: Literal["cold_target"] | None
    top_100_item_ids: tuple[str, ...]

    @field_validator("sample_id", "user_id", "target_item_id", "cutoff_identity")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("candidate_count")
    @classmethod
    def _validate_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("candidate_count must be non-negative")
        return value

    @field_validator("target_rank")
    @classmethod
    def _validate_rank(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("target_rank must be one-based")
        return value

    @model_validator(mode="after")
    def _validate_outcome(self) -> "TargetRankingOutcome":
        require_unique(self.top_100_item_ids, "Top-100 item IDs")
        if len(self.top_100_item_ids) > min(100, self.candidate_count):
            raise ValueError("Top-100 output exceeds candidate coverage")
        if self.warm_target:
            if self.target_rank is None or self.miss_reason is not None:
                raise ValueError("warm target requires an exact rank")
            if self.target_rank > self.candidate_count:
                raise ValueError("target rank exceeds candidate count")
        elif self.target_rank is not None or self.miss_reason != "cold_target":
            raise ValueError("cold target requires an explicit cold miss")
        return self


class MetricAggregate(FrozenModel):
    numerator: float
    denominator: int
    mean: float

    @field_validator("numerator", "mean")
    @classmethod
    def _validate_finite(cls, value: float, info: ValidationInfo) -> float:
        return require_finite(value, info.field_name)

    @field_validator("denominator")
    @classmethod
    def _validate_denominator(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("metric denominator must be positive")
        return value

    @model_validator(mode="after")
    def _validate_mean(self) -> "MetricAggregate":
        expected = self.numerator / self.denominator
        if abs(self.mean - expected) > 1e-12:
            raise ValueError("metric mean does not equal numerator/denominator")
        return self


class RankingEvaluationAggregate(FrozenModel):
    schema_version: Literal["p3-ranking-evaluation-aggregate-v1"]
    split: Literal["validation", "test"]
    all_target_count: int
    warm_target_count: int
    cold_target_count: int
    all_target_retrieval_coverage: MetricAggregate
    warm_metrics: dict[
        Literal["ndcg_at_10", "hr_at_10", "ndcg_at_20", "hr_at_20", "mrr_at_10", "recall_at_100"],
        MetricAggregate,
    ]

    @field_validator("all_target_count", "warm_target_count", "cold_target_count")
    @classmethod
    def _validate_counts(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_aggregate(self) -> "RankingEvaluationAggregate":
        if self.all_target_count <= 0:
            raise ValueError("evaluation subset must not be empty")
        if self.warm_target_count <= 0:
            raise ValueError("warm evaluation subset must not be empty")
        if self.warm_target_count + self.cold_target_count != self.all_target_count:
            raise ValueError("warm/cold counts must partition all targets")
        if set(self.warm_metrics) != {
            "ndcg_at_10",
            "hr_at_10",
            "ndcg_at_20",
            "hr_at_20",
            "mrr_at_10",
            "recall_at_100",
        }:
            raise ValueError("warm metric inventory mismatch")
        if any(
            metric.denominator != self.warm_target_count for metric in self.warm_metrics.values()
        ):
            raise ValueError("warm metric denominator mismatch")
        coverage = self.all_target_retrieval_coverage
        if coverage.denominator != self.all_target_count or coverage.numerator != float(
            self.warm_target_count
        ):
            raise ValueError("retrieval coverage count mismatch")
        return self
