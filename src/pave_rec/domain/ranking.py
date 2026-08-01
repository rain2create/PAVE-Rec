"""Initial ranking schemas."""

from pydantic import field_validator, model_validator

from .base import FrozenModel, JsonObject, require_finite, require_non_empty, require_unique
from .refs import ResourceRef


class InitialRankedCandidate(FrozenModel):
    item_id: str
    score: float
    rank: int

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")

    @field_validator("score")
    @classmethod
    def _validate_score(cls, value: float) -> float:
        return require_finite(value, "score")

    @field_validator("rank")
    @classmethod
    def _validate_rank(cls, value: int) -> int:
        if value < 1:
            raise ValueError("rank must start at 1")
        return value


class InitialRankingOutput(FrozenModel):
    candidates: tuple[InitialRankedCandidate, ...]
    user_sequence_feature_ref: ResourceRef | None = None
    metadata: JsonObject

    @model_validator(mode="after")
    def _validate_ranking(self) -> "InitialRankingOutput":
        if not self.candidates:
            raise ValueError("initial ranking must contain at least one candidate")
        require_unique(tuple(candidate.item_id for candidate in self.candidates), "candidate IDs")
        ranks = tuple(candidate.rank for candidate in self.candidates)
        expected = tuple(range(1, len(self.candidates) + 1))
        if ranks != expected:
            raise ValueError("initial ranking must be ordered by contiguous ranks starting at 1")
        return self
