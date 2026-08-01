"""Strict loader for the versioned deterministic Phase 1 fixture."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError, field_validator, model_validator

from .domain import (
    CandidateScore,
    InformationNeed,
    InitialRankingOutput,
    ItemFeatureRef,
    ItemSegmentCatalog,
    PerceptionResult,
    SegmentValue,
    UserMemoryView,
)
from .domain.base import FrozenModel, require_non_empty, require_unique
from .errors import FixtureValidationError


class FixtureInput(FrozenModel):
    user_id: str
    history: tuple[str, ...]
    candidate_ids: tuple[str, ...]

    @field_validator("user_id")
    @classmethod
    def _validate_user_id(cls, value: str) -> str:
        return require_non_empty(value, "user_id")

    @model_validator(mode="after")
    def _validate_items(self) -> "FixtureInput":
        for value in (*self.history, *self.candidate_ids):
            require_non_empty(value, "fixture item ID")
        if not self.candidate_ids:
            raise ValueError("fixture candidate_ids must not be empty")
        require_unique(self.candidate_ids, "fixture candidate IDs")
        return self


class EvidenceScoreDelta(FrozenModel):
    evidence_id: str
    deltas: tuple[CandidateScore, ...]

    @field_validator("evidence_id")
    @classmethod
    def _validate_evidence_id(cls, value: str) -> str:
        return require_non_empty(value, "evidence_id")


class MockFixture(FrozenModel):
    fixture_version: str
    input: FixtureInput
    user_memory: UserMemoryView
    initial_ranking: InitialRankingOutput
    item_feature_refs: tuple[ItemFeatureRef, ...]
    segment_catalog: tuple[ItemSegmentCatalog, ...]
    information_need: InformationNeed
    segment_values: tuple[SegmentValue, ...]
    perception_results: tuple[PerceptionResult, ...]
    score_deltas: tuple[EvidenceScoreDelta, ...]

    @field_validator("fixture_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        return require_non_empty(value, "fixture_version")

    @model_validator(mode="after")
    def _validate_fixture_coverage(self) -> "MockFixture":
        candidate_ids = self.input.candidate_ids
        ranking_ids = tuple(candidate.item_id for candidate in self.initial_ranking.candidates)
        feature_ids = tuple(entry.item_id for entry in self.item_feature_refs)
        catalog_ids = tuple(entry.item_id for entry in self.segment_catalog)
        if (
            ranking_ids != candidate_ids
            or feature_ids != candidate_ids
            or catalog_ids != candidate_ids
        ):
            raise ValueError("ranking and store outputs must match fixture candidate order")

        segment_identities = tuple(
            (segment.item_id, segment.segment_id)
            for catalog in self.segment_catalog
            for segment in catalog.segments
        )
        value_identities = tuple((value.item_id, value.segment_id) for value in self.segment_values)
        result_identities = tuple(
            (result.item_id, result.segment_id) for result in self.perception_results
        )
        canonical_identities = tuple(sorted(segment_identities))
        if value_identities != canonical_identities or result_identities != canonical_identities:
            raise ValueError(
                "fixture values/results must cover all segments in canonical identity order"
            )
        require_unique(value_identities, "fixture segment-value identities")
        require_unique(result_identities, "fixture perception-result identities")

        atom_ids = {
            atom.atom_id
            for atom in (*self.user_memory.long_term_atoms, *self.user_memory.short_term_atoms)
        }
        if not set(self.information_need.relevant_preference_atom_ids).issubset(atom_ids):
            raise ValueError("fixture information need references unknown preference atoms")

        evidence_ids = tuple(
            result.evidence.evidence_id
            for result in self.perception_results
            if result.evidence is not None
        )
        delta_ids = tuple(entry.evidence_id for entry in self.score_deltas)
        require_unique(evidence_ids, "fixture evidence IDs")
        require_unique(delta_ids, "fixture score-delta evidence IDs")
        if delta_ids != evidence_ids:
            raise ValueError("fixture score deltas must follow and cover successful evidence")
        for entry in self.score_deltas:
            if tuple(delta.item_id for delta in entry.deltas) != candidate_ids:
                raise ValueError("every score-delta row must cover candidates in input order")
        return self


def load_fixture(path: Path, *, expected_version: str) -> MockFixture:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FixtureValidationError(f"cannot read fixture {path.name}: {exc}") from exc
    try:
        fixture = MockFixture.model_validate_json(data)
    except ValidationError as exc:
        raise FixtureValidationError(f"invalid mock fixture: {exc}") from exc
    if fixture.fixture_version != expected_version:
        raise FixtureValidationError(
            f"fixture version {fixture.fixture_version!r} does not match {expected_version!r}"
        )
    return fixture
