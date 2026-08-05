"""Strict logical records for the versioned Phase 3 derived sequence dataset."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.domain.base import FrozenModel, require_non_empty, require_unique
from pave_rec.preprocessing.identity import validate_data_version
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key

SPLIT_RECIPE = "user-chronological-leave-two-out-v1"
ELIGIBILITY_RECIPE = "min-positive-5"
SASREC_VIEW_RECIPE = "sasrec-recent-50-v1"
VOCABULARY_RECIPE = "train-positive-utf8-order-pad0-v1"
PRIMARY_CANDIDATE_RECIPE = "full-train-vocabulary-seen-positive-mask-v1"
DEV_CANDIDATE_RECIPE = "warm-target-plus-100-train-negatives-v1"
DERIVED_BUILDER_VERSION = "p3-derived-dataset-builder-v1"
DERIVED_VERSION_PATTERN = re.compile(r"^p3derived-[0-9a-f]{64}$")
DERIVED_COUNT_KEYS = frozenset(
    {
        "development_candidate_sets",
        "eligible_users",
        "test_cold_targets",
        "test_targets",
        "test_warm_targets",
        "train_events",
        "training_samples",
        "validation_cold_targets",
        "validation_targets",
        "validation_warm_targets",
        "vocabulary_items",
    }
)


class DerivedPositiveEvent(FrozenModel):
    item_id: str
    source_interaction_index: int
    occurred_at_ms: int

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")

    @field_validator("source_interaction_index", "occurred_at_ms")
    @classmethod
    def _validate_non_negative(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value


class DerivedTarget(FrozenModel):
    sample_id: str
    user_id: str
    split: Literal["validation", "test"]
    history: tuple[DerivedPositiveEvent, ...]
    target: DerivedPositiveEvent
    history_end_interaction_index_exclusive: int
    cutoff_identity: str
    in_train_vocabulary: bool

    @field_validator("sample_id", "user_id", "cutoff_identity")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_temporal_boundary(self) -> "DerivedTarget":
        if not self.history:
            raise ValueError("evaluation target history must not be empty")
        indexes = tuple(event.source_interaction_index for event in self.history)
        if indexes != tuple(sorted(indexes)):
            raise ValueError("target history must preserve source interaction order")
        if any(index >= self.history_end_interaction_index_exclusive for index in indexes):
            raise ValueError("target history crosses the exclusive full-exposure cutoff")
        if self.target.source_interaction_index != self.history_end_interaction_index_exclusive:
            raise ValueError("target interaction index must equal the exclusive cutoff")
        return self


class DerivedUserSplit(FrozenModel):
    user_id: str
    train_events: tuple[DerivedPositiveEvent, ...]
    validation_target: DerivedTarget
    test_target: DerivedTarget

    @field_validator("user_id")
    @classmethod
    def _validate_user_id(cls, value: str) -> str:
        return require_non_empty(value, "user_id")

    @model_validator(mode="after")
    def _validate_split(self) -> "DerivedUserSplit":
        if len(self.train_events) < 3:
            raise ValueError("eligible user split requires at least three train positives")
        if (
            self.validation_target.user_id != self.user_id
            or self.test_target.user_id != self.user_id
        ):
            raise ValueError("split target user identity mismatch")
        if self.validation_target.split != "validation" or self.test_target.split != "test":
            raise ValueError("split target roles are invalid")
        if self.validation_target.history != self.train_events:
            raise ValueError("validation history must equal the train positive sequence")
        if self.test_target.history != (*self.train_events, self.validation_target.target):
            raise ValueError("test history must equal train positives plus validation target")
        return self


class TrainingSample(FrozenModel):
    sample_id: str
    user_id: str
    history: tuple[DerivedPositiveEvent, ...]
    target: DerivedPositiveEvent
    history_end_interaction_index_exclusive: int

    @field_validator("sample_id", "user_id")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_prefix(self) -> "TrainingSample":
        if not self.history:
            raise ValueError("training sample history must not be empty")
        if self.target.source_interaction_index != self.history_end_interaction_index_exclusive:
            raise ValueError("training target must define the exclusive cutoff")
        if any(
            event.source_interaction_index >= self.history_end_interaction_index_exclusive
            for event in self.history
        ):
            raise ValueError("training history crosses its target cutoff")
        return self


class VocabularyEntry(FrozenModel):
    item_id: str
    model_index: int

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return require_non_empty(value, "item_id")

    @field_validator("model_index")
    @classmethod
    def _validate_index(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("model_index must be positive; PAD owns index zero")
        return value


class TrainVocabulary(FrozenModel):
    schema_version: Literal["p3-train-vocabulary-v1"]
    recipe: Literal["train-positive-utf8-order-pad0-v1"]
    pad_index: Literal[0]
    entries: tuple[VocabularyEntry, ...]

    @model_validator(mode="after")
    def _validate_entries(self) -> "TrainVocabulary":
        if not self.entries:
            raise ValueError("train vocabulary must not be empty")
        item_ids = tuple(entry.item_id for entry in self.entries)
        require_unique(item_ids, "vocabulary item IDs")
        expected_items = tuple(sorted(item_ids, key=lambda value: value.encode("utf-8")))
        if item_ids != expected_items:
            raise ValueError("vocabulary items must use canonical UTF-8 byte order")
        if tuple(entry.model_index for entry in self.entries) != tuple(
            range(1, len(self.entries) + 1)
        ):
            raise ValueError("vocabulary model indexes must be contiguous from one")
        return self


class EvaluationSubset(FrozenModel):
    schema_version: Literal["p3-evaluation-subset-v1"]
    split: Literal["validation", "test"]
    all_target_sample_ids: tuple[str, ...]
    warm_target_sample_ids: tuple[str, ...]
    cold_target_sample_ids: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_partition(self) -> "EvaluationSubset":
        require_unique(self.all_target_sample_ids, "all target sample IDs")
        require_unique(self.warm_target_sample_ids, "warm target sample IDs")
        require_unique(self.cold_target_sample_ids, "cold target sample IDs")
        if set(self.warm_target_sample_ids).intersection(self.cold_target_sample_ids):
            raise ValueError("warm and cold target subsets must not overlap")
        if set(self.all_target_sample_ids) != set(self.warm_target_sample_ids).union(
            self.cold_target_sample_ids
        ):
            raise ValueError("warm/cold target subsets must partition all targets")
        return self


class DevelopmentCandidateSet(FrozenModel):
    schema_version: Literal["p3-development-candidates-v1"]
    recipe: Literal["warm-target-plus-100-train-negatives-v1"]
    seed: Literal[20260804]
    target_sample_id: str
    target_item_id: str
    history_item_ids: tuple[str, ...]
    negative_item_ids: tuple[str, ...]

    @field_validator("target_sample_id", "target_item_id")
    @classmethod
    def _validate_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_candidates(self) -> "DevelopmentCandidateSet":
        if self.seed < 0:
            raise ValueError("development candidate seed must be non-negative")
        require_unique(self.negative_item_ids, "development negative item IDs")
        if len(self.negative_item_ids) != 100:
            raise ValueError("development candidate set requires exactly 100 negatives")
        if self.target_item_id in self.negative_item_ids:
            raise ValueError("development negatives contain the labeled target")
        if set(self.history_item_ids).intersection(self.negative_item_ids):
            raise ValueError("development negatives contain cutoff-prefix positives")
        expected = tuple(sorted(self.negative_item_ids, key=lambda value: value.encode("utf-8")))
        if self.negative_item_ids != expected:
            raise ValueError("development negatives must use canonical UTF-8 byte order")
        return self


class DerivedDatasetManifest(FrozenModel):
    schema_version: Literal["p3-derived-dataset-manifest-v1"]
    derived_version: str
    source_data_version: str
    source_release_ref: ResourceRef
    positive_recipe: Literal["tsv-positive-v1"]
    split_recipe: Literal["user-chronological-leave-two-out-v1"]
    eligibility_recipe: Literal["min-positive-5"]
    sasrec_view_recipe: Literal["sasrec-recent-50-v1"]
    max_history_length: Literal[50]
    vocabulary_recipe: Literal["train-positive-utf8-order-pad0-v1"]
    primary_candidate_recipe: Literal["full-train-vocabulary-seen-positive-mask-v1"]
    development_candidate_recipe: Literal["warm-target-plus-100-train-negatives-v1"] | None
    eval_negative_seed: Literal[20260804] | None
    payload_refs: tuple[ResourceRef, ...]
    counts: dict[str, int]

    @field_validator("derived_version", "source_data_version")
    @classmethod
    def _validate_versions(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_manifest(self) -> "DerivedDatasetManifest":
        if DERIVED_VERSION_PATTERN.fullmatch(self.derived_version) is None:
            raise ValueError("derived_version must be p3derived-<64 lowercase hex>")
        try:
            validate_data_version(self.source_data_version)
            require_sha256(
                self.source_release_ref.checksum,
                "source_release_ref.checksum",
            )
            validate_filesystem_key(self.source_release_ref.key)
        except ValueError as exc:
            raise ValueError(f"invalid source release identity: {exc}") from exc
        if (
            self.source_release_ref.version != self.source_data_version
            or self.source_release_ref.key != f"releases/{self.source_data_version}.json"
        ):
            raise ValueError("source release key/version mismatch")
        if (self.development_candidate_recipe is None) != (self.eval_negative_seed is None):
            raise ValueError("development recipe and seed must be both present or both absent")
        keys = tuple((ref.store, ref.key) for ref in self.payload_refs)
        require_unique(keys, "derived payload refs")
        if keys != tuple(sorted(keys)):
            raise ValueError("derived payload refs must use canonical store/key order")
        expected_names = {
            "test_subset.json",
            "training_samples.jsonl",
            "user_splits.jsonl",
            "validation_subset.json",
            "vocabulary.json",
        }
        if self.development_candidate_recipe is not None:
            expected_names.add("development_candidates.jsonl")
        prefix = f"bundles/{self.derived_version}/"
        names: set[str] = set()
        stores: set[str] = set()
        for ref in self.payload_refs:
            try:
                require_sha256(ref.checksum, "payload_ref.checksum")
                validate_filesystem_key(ref.key)
            except ValueError as exc:
                raise ValueError(f"invalid derived payload ref: {exc}") from exc
            if ref.version != self.derived_version or not ref.key.startswith(prefix):
                raise ValueError("derived payload key/version mismatch")
            name = ref.key.removeprefix(prefix)
            if "/" in name:
                raise ValueError("derived payload must be a direct bundle member")
            names.add(name)
            stores.add(ref.store)
        if names != expected_names or len(stores) != 1:
            raise ValueError("derived payload inventory mismatch")
        if set(self.counts) != DERIVED_COUNT_KEYS:
            raise ValueError("derived manifest count inventory mismatch")
        if any(value < 0 for value in self.counts.values()):
            raise ValueError("derived manifest counts must be non-negative")
        return self
