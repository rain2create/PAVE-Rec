"""Deterministic no-leakage construction of Phase 3 logical sequence records."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from pave_rec.domain import ResourceRef
from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import DatasetValidationError
from pave_rec.phase3.tsinghua import classify_tsinghua_interaction
from pave_rec.preprocessing.identity import validate_data_version
from pave_rec.preprocessing.models import SequenceInteraction, UserBehaviorSequence
from pave_rec.preprocessing.paths import require_sha256

from .models import (
    DEV_CANDIDATE_RECIPE,
    DerivedPositiveEvent,
    DerivedTarget,
    DerivedUserSplit,
    DevelopmentCandidateSet,
    EvaluationSubset,
    TrainingSample,
    TrainVocabulary,
    VocabularyEntry,
)

MIN_POSITIVES = 5
MAX_HISTORY_LENGTH = 50
EVAL_NEGATIVE_SEED = 20260804


@dataclass(frozen=True)
class DerivedDataset:
    source_data_version: str
    source_release_ref: ResourceRef
    user_splits: tuple[DerivedUserSplit, ...]
    training_samples: tuple[TrainingSample, ...]
    vocabulary: TrainVocabulary
    validation_subset: EvaluationSubset
    test_subset: EvaluationSubset
    development_candidate_recipe: str | None
    eval_negative_seed: int | None
    development_candidates: tuple[DevelopmentCandidateSet, ...]


def _identity(prefix: str, record: dict[str, object]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(record, pretty=False)).hexdigest()
    return f"{prefix}-{digest}"


def _positive_event(interaction: SequenceInteraction) -> DerivedPositiveEvent:
    if interaction.occurred_at_ms is None:
        raise DatasetValidationError("Tsinghua derived events require source timestamps")
    return DerivedPositiveEvent(
        item_id=interaction.item_id,
        source_interaction_index=interaction.interaction_index,
        occurred_at_ms=interaction.occurred_at_ms,
    )


def _target(
    *,
    data_version: str,
    user_id: str,
    split: str,
    history: tuple[DerivedPositiveEvent, ...],
    target: DerivedPositiveEvent,
    vocabulary_items: frozenset[str],
) -> DerivedTarget:
    cutoff_record = {
        "schema_version": "p3-full-exposure-cutoff-v1",
        "source_data_version": data_version,
        "user_id": user_id,
        "history_end_interaction_index_exclusive": target.source_interaction_index,
    }
    cutoff_identity = _identity("p3cutoff", cutoff_record)
    sample_record = {
        "schema_version": "p3-evaluation-target-v1",
        "source_data_version": data_version,
        "user_id": user_id,
        "split": split,
        "target_interaction_index": target.source_interaction_index,
        "target_item_id": target.item_id,
        "cutoff_identity": cutoff_identity,
    }
    return DerivedTarget(
        sample_id=_identity("p3target", sample_record),
        user_id=user_id,
        split=split,
        history=history,
        target=target,
        history_end_interaction_index_exclusive=target.source_interaction_index,
        cutoff_identity=cutoff_identity,
        in_train_vocabulary=target.item_id in vocabulary_items,
    )


def _training_samples(
    data_version: str,
    user_id: str,
    train_events: tuple[DerivedPositiveEvent, ...],
) -> tuple[TrainingSample, ...]:
    samples = []
    for target_position in range(1, len(train_events)):
        target = train_events[target_position]
        record = {
            "schema_version": "p3-training-sample-v1",
            "source_data_version": data_version,
            "user_id": user_id,
            "target_interaction_index": target.source_interaction_index,
            "target_item_id": target.item_id,
        }
        samples.append(
            TrainingSample(
                sample_id=_identity("p3train", record),
                user_id=user_id,
                history=train_events[:target_position],
                target=target,
                history_end_interaction_index_exclusive=target.source_interaction_index,
            )
        )
    return tuple(samples)


def _subset(split: str, targets: tuple[DerivedTarget, ...]) -> EvaluationSubset:
    all_ids = tuple(target.sample_id for target in targets)
    warm = tuple(target.sample_id for target in targets if target.in_train_vocabulary)
    cold = tuple(target.sample_id for target in targets if not target.in_train_vocabulary)
    return EvaluationSubset(
        schema_version="p3-evaluation-subset-v1",
        split=split,
        all_target_sample_ids=all_ids,
        warm_target_sample_ids=warm,
        cold_target_sample_ids=cold,
    )


def _candidate_walk(seed: int, sample_id: str, domain_size: int) -> tuple[int, int]:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "recipe": DEV_CANDIDATE_RECIPE,
                "seed": seed,
                "target_sample_id": sample_id,
            },
            pretty=False,
        )
    ).digest()
    start = int.from_bytes(digest[:16], "big") % domain_size
    step = int.from_bytes(digest[16:], "big") % domain_size
    if step == 0:
        step = 1
    while math.gcd(step, domain_size) != 1:
        step = (step + 1) % domain_size
        if step == 0:
            step = 1
    return start, step


def build_development_candidates(
    *,
    targets: tuple[DerivedTarget, ...],
    vocabulary: TrainVocabulary,
    seed: int = EVAL_NEGATIVE_SEED,
) -> tuple[DevelopmentCandidateSet, ...]:
    if seed != EVAL_NEGATIVE_SEED:
        raise DatasetValidationError(
            f"development candidate seed must be fixed at {EVAL_NEGATIVE_SEED}"
        )
    vocabulary_items = tuple(entry.item_id for entry in vocabulary.entries)
    vocabulary_set = frozenset(vocabulary_items)
    result = []
    for target in targets:
        if not target.in_train_vocabulary:
            continue
        excluded = {target.target.item_id, *(event.item_id for event in target.history)}
        available = len(vocabulary_items) - len(excluded.intersection(vocabulary_set))
        if available < 100:
            raise DatasetValidationError(
                f"insufficient train-vocabulary negatives for target {target.sample_id}"
            )
        start, step = _candidate_walk(seed, target.sample_id, len(vocabulary_items))
        selected: list[str] = []
        offset = 0
        while len(selected) < 100:
            item_id = vocabulary_items[(start + offset * step) % len(vocabulary_items)]
            offset += 1
            if item_id not in excluded:
                selected.append(item_id)
        result.append(
            DevelopmentCandidateSet(
                schema_version="p3-development-candidates-v1",
                recipe=DEV_CANDIDATE_RECIPE,
                seed=seed,
                target_sample_id=target.sample_id,
                target_item_id=target.target.item_id,
                history_item_ids=tuple(event.item_id for event in target.history),
                negative_item_ids=tuple(sorted(selected, key=lambda value: value.encode("utf-8"))),
            )
        )
    return tuple(result)


def build_derived_dataset(
    *,
    sequences: tuple[UserBehaviorSequence, ...],
    source_data_version: str,
    source_release_ref: ResourceRef,
    include_development_candidates: bool,
    eval_negative_seed: int = EVAL_NEGATIVE_SEED,
) -> DerivedDataset:
    """Build all logical records using only canonical P2 ordering and train facts."""

    try:
        validate_data_version(source_data_version)
        require_sha256(source_release_ref.checksum, "source_release_ref.checksum")
    except ValueError as exc:
        raise DatasetValidationError(f"invalid P3 derived source identity: {exc}") from exc
    if source_release_ref.version != source_data_version:
        raise DatasetValidationError("source release ref/data version mismatch")
    if eval_negative_seed != EVAL_NEGATIVE_SEED:
        raise DatasetValidationError(f"eval_negative_seed must be fixed at {EVAL_NEGATIVE_SEED}")
    user_ids = tuple(sequence.user_id for sequence in sequences)
    if user_ids != tuple(sorted(user_ids)) or len(user_ids) != len(set(user_ids)):
        raise DatasetValidationError("P2 sequences must use unique canonical user order")

    eligible: list[tuple[str, tuple[DerivedPositiveEvent, ...]]] = []
    for sequence in sequences:
        positives = tuple(
            _positive_event(interaction)
            for interaction in sequence.interactions
            if classify_tsinghua_interaction(interaction) == "positive_v1"
        )
        if len(positives) >= MIN_POSITIVES:
            eligible.append((sequence.user_id, positives))
    if not eligible:
        raise DatasetValidationError("no users satisfy min-positive-5 eligibility")

    train_item_ids = {event.item_id for _, positives in eligible for event in positives[:-2]}
    ordered_items = tuple(sorted(train_item_ids, key=lambda value: value.encode("utf-8")))
    vocabulary = TrainVocabulary(
        schema_version="p3-train-vocabulary-v1",
        recipe="train-positive-utf8-order-pad0-v1",
        pad_index=0,
        entries=tuple(
            VocabularyEntry(item_id=item_id, model_index=index)
            for index, item_id in enumerate(ordered_items, start=1)
        ),
    )
    vocabulary_set = frozenset(ordered_items)

    splits: list[DerivedUserSplit] = []
    training_samples: list[TrainingSample] = []
    validation_targets: list[DerivedTarget] = []
    test_targets: list[DerivedTarget] = []
    for user_id, positives in eligible:
        train = positives[:-2]
        validation = _target(
            data_version=source_data_version,
            user_id=user_id,
            split="validation",
            history=train,
            target=positives[-2],
            vocabulary_items=vocabulary_set,
        )
        test = _target(
            data_version=source_data_version,
            user_id=user_id,
            split="test",
            history=positives[:-1],
            target=positives[-1],
            vocabulary_items=vocabulary_set,
        )
        splits.append(
            DerivedUserSplit(
                user_id=user_id,
                train_events=train,
                validation_target=validation,
                test_target=test,
            )
        )
        training_samples.extend(_training_samples(source_data_version, user_id, train))
        validation_targets.append(validation)
        test_targets.append(test)

    all_targets = (*validation_targets, *test_targets)
    development = (
        build_development_candidates(
            targets=all_targets,
            vocabulary=vocabulary,
            seed=eval_negative_seed,
        )
        if include_development_candidates
        else ()
    )
    return DerivedDataset(
        source_data_version=source_data_version,
        source_release_ref=source_release_ref,
        user_splits=tuple(splits),
        training_samples=tuple(training_samples),
        vocabulary=vocabulary,
        validation_subset=_subset("validation", tuple(validation_targets)),
        test_subset=_subset("test", tuple(test_targets)),
        development_candidate_recipe=(
            DEV_CANDIDATE_RECIPE if include_development_candidates else None
        ),
        eval_negative_seed=(eval_negative_seed if include_development_candidates else None),
        development_candidates=development,
    )
