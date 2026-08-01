"""Read-only user-memory views shared with the agent harness."""

from pydantic import ValidationInfo, field_validator, model_validator

from .base import (
    FrozenModel,
    JsonObject,
    require_finite,
    require_non_empty,
    require_range,
    require_unique,
)
from .enums import PreferenceMatchType, PreferenceState
from .refs import ResourceRef


class PreferenceAtomView(FrozenModel):
    atom_id: str
    text: str
    state: PreferenceState
    strength: float
    persistence: float
    created_at_ms: int | None = None
    last_seen_at_ms: int | None = None
    embedding_ref: ResourceRef | None = None
    metadata: JsonObject

    @field_validator("atom_id", "text")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("strength", "persistence")
    @classmethod
    def _validate_unit_values(cls, value: float, info: ValidationInfo) -> float:
        return require_range(value, info.field_name, 0.0, 1.0)


class PreferenceMatchView(FrozenModel):
    long_atom_id: str | None = None
    short_atom_id: str | None = None
    similarity: float | None = None
    classification: PreferenceMatchType

    @field_validator("long_atom_id", "short_atom_id")
    @classmethod
    def _validate_optional_ids(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None:
            return require_non_empty(value, info.field_name)
        return value

    @field_validator("similarity")
    @classmethod
    def _validate_similarity(cls, value: float | None) -> float | None:
        if value is not None:
            return require_range(value, "similarity", -1.0, 1.0)
        return value

    @model_validator(mode="after")
    def _validate_identity(self) -> "PreferenceMatchView":
        if self.long_atom_id is None and self.short_atom_id is None:
            raise ValueError("a preference match must reference at least one atom")
        return self


class UserMemoryView(FrozenModel):
    long_term_atoms: tuple[PreferenceAtomView, ...]
    short_term_atoms: tuple[PreferenceAtomView, ...]
    preference_matches: tuple[PreferenceMatchView, ...]
    global_drift: float | None = None
    new_interest_drift: float | None = None
    drop_interest_drift: float | None = None
    semantic_profile: str | None = None
    similarity_matrix_ref: ResourceRef | None = None
    memory_version: str
    updated_at_ms: int | None = None
    metadata: JsonObject

    @field_validator("global_drift", "new_interest_drift", "drop_interest_drift")
    @classmethod
    def _validate_drift(cls, value: float | None, info: ValidationInfo) -> float | None:
        if value is not None:
            return require_finite(value, info.field_name)
        return value

    @field_validator("semantic_profile")
    @classmethod
    def _validate_profile(cls, value: str | None) -> str | None:
        if value is not None:
            return require_non_empty(value, "semantic_profile")
        return value

    @field_validator("memory_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        return require_non_empty(value, "memory_version")

    @model_validator(mode="after")
    def _validate_atom_references(self) -> "UserMemoryView":
        long_ids = tuple(atom.atom_id for atom in self.long_term_atoms)
        short_ids = tuple(atom.atom_id for atom in self.short_term_atoms)
        require_unique(long_ids + short_ids, "user-memory atom IDs")
        long_set = set(long_ids)
        short_set = set(short_ids)
        for match in self.preference_matches:
            if match.long_atom_id is not None and match.long_atom_id not in long_set:
                raise ValueError(f"unknown long-term atom: {match.long_atom_id}")
            if match.short_atom_id is not None and match.short_atom_id not in short_set:
                raise ValueError(f"unknown short-term atom: {match.short_atom_id}")
        return self
