"""Torch-free deterministic SASRec ordering and negative sampling."""

from __future__ import annotations

import hashlib

from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import DatasetValidationError

NEGATIVE_SAMPLER_RECIPE = "uniform-train-vocabulary-user-train-exclusion-v1"
EPOCH_ORDER_RECIPE = "sha256-training-seed-epoch-sample-id-order-v1"


def epoch_sample_order(
    sample_ids: tuple[str, ...],
    *,
    training_seed: int,
    epoch: int,
) -> tuple[int, ...]:
    if training_seed < 0 or epoch <= 0:
        raise DatasetValidationError("training seed must be non-negative and epoch positive")
    return tuple(
        sorted(
            range(len(sample_ids)),
            key=lambda index: (
                hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "recipe": EPOCH_ORDER_RECIPE,
                            "training_seed": training_seed,
                            "epoch": epoch,
                            "sample_id": sample_ids[index],
                        },
                        pretty=False,
                    )
                ).digest(),
                sample_ids[index],
            ),
        )
    )


def deterministic_uniform_negative(
    *,
    vocabulary_size: int,
    excluded_model_indices: frozenset[int],
    training_seed: int,
    epoch: int,
    sample_id: str,
    negative_index: int = 0,
) -> int:
    """Choose one known item without consulting validation/test labels."""

    if vocabulary_size <= 0:
        raise DatasetValidationError("negative sampler requires a non-empty vocabulary")
    if any(index <= 0 or index > vocabulary_size for index in excluded_model_indices):
        raise DatasetValidationError("negative sampler exclusion is outside the vocabulary")
    if len(excluded_model_indices) >= vocabulary_size:
        raise DatasetValidationError("user train positives exhaust the negative domain")
    if training_seed < 0 or epoch <= 0 or negative_index < 0 or not sample_id:
        raise DatasetValidationError("invalid deterministic negative-sampler key")
    counter = 0
    while True:
        digest = hashlib.sha256(
            canonical_json_bytes(
                {
                    "recipe": NEGATIVE_SAMPLER_RECIPE,
                    "training_seed": training_seed,
                    "epoch": epoch,
                    "sample_id": sample_id,
                    "negative_index": negative_index,
                    "counter": counter,
                },
                pretty=False,
            )
        ).digest()
        candidate = int.from_bytes(digest[:8], "big") % vocabulary_size + 1
        if candidate not in excluded_model_indices:
            return candidate
        counter += 1
