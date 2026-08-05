"""Strict config for the P3-02 derived-sequence lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.phase3.config import LoadedPhase3Config, Phase3ConfigBase, load_phase3_config
from pave_rec.preprocessing.identity import validate_data_version
from pave_rec.preprocessing.paths import (
    require_sha256,
    validate_filesystem_key,
    validate_root_id,
)

from .builder import EVAL_NEGATIVE_SEED, MAX_HISTORY_LENGTH
from .models import (
    ELIGIBILITY_RECIPE,
    PRIMARY_CANDIDATE_RECIPE,
    SASREC_VIEW_RECIPE,
    SPLIT_RECIPE,
    VOCABULARY_RECIPE,
)


class Phase3DerivedSequencesConfig(Phase3ConfigBase):
    kind: Literal["phase3-derived-sequences"]
    source_release_ref: ResourceRef
    output_root_id: str
    positive_recipe: Literal["tsv-positive-v1"]
    split_recipe: Literal["user-chronological-leave-two-out-v1"]
    eligibility_recipe: Literal["min-positive-5"]
    sasrec_view_recipe: Literal["sasrec-recent-50-v1"]
    max_history_length: Literal[50]
    vocabulary_recipe: Literal["train-positive-utf8-order-pad0-v1"]
    primary_candidate_recipe: Literal["full-train-vocabulary-seen-positive-mask-v1"]
    include_development_candidates: Literal[True]
    eval_negative_seed: Literal[20260804]

    @field_validator("output_root_id")
    @classmethod
    def _validate_output_root_id(cls, value: str) -> str:
        return validate_root_id(value)

    @model_validator(mode="after")
    def _validate_source_and_roots(self) -> "Phase3DerivedSequencesConfig":
        try:
            validate_data_version(self.source_release_ref.version)
            require_sha256(self.source_release_ref.checksum)
            validate_filesystem_key(self.source_release_ref.key)
        except ValueError as exc:
            raise ValueError(f"invalid source_release_ref: {exc}") from exc
        if self.source_release_ref.key != f"releases/{self.source_release_ref.version}.json":
            raise ValueError("source_release_ref key/version mismatch")
        source_root = self.storage.roots.get(self.source_release_ref.store)
        output_root = self.storage.roots.get(self.output_root_id)
        if source_root is None or source_root.access != "read_only":
            raise ValueError("source_release_ref must use a declared read_only root")
        if output_root is None or output_root.access != "write_new":
            raise ValueError("output_root_id must reference a declared write_new root")
        if self.source_release_ref.store == self.output_root_id:
            raise ValueError("source release and derived output roots must be distinct")
        if (
            self.split_recipe != SPLIT_RECIPE
            or self.eligibility_recipe != ELIGIBILITY_RECIPE
            or self.sasrec_view_recipe != SASREC_VIEW_RECIPE
            or self.max_history_length != MAX_HISTORY_LENGTH
            or self.vocabulary_recipe != VOCABULARY_RECIPE
            or self.primary_candidate_recipe != PRIMARY_CANDIDATE_RECIPE
            or self.eval_negative_seed != EVAL_NEGATIVE_SEED
        ):
            raise ValueError("derived recipe constants are inconsistent")
        return self


def load_phase3_derived_sequences_config(
    config_path: str | Path,
) -> LoadedPhase3Config[Phase3DerivedSequencesConfig]:
    return load_phase3_config(config_path, Phase3DerivedSequencesConfig)
