"""Pluggable Phase 3 initial-ranker contracts with lazy optional Torch imports."""

from __future__ import annotations

from typing import Any

from .checkpoint_models import (
    CHECKPOINT_IDENTITY_SCHEMA,
    CHECKPOINT_SCHEMA,
    CheckpointPayload,
    CheckpointPublicationResult,
    SasrecCheckpointManifest,
)
from .config import (
    Phase3SasrecTrainingConfig,
    SasrecModelConfig,
    SasrecOperationalConfig,
    SasrecTrainingRecipeConfig,
    load_phase3_sasrec_training_config,
)
from .sampler import (
    EPOCH_ORDER_RECIPE,
    NEGATIVE_SAMPLER_RECIPE,
    deterministic_uniform_negative,
    epoch_sample_order,
)

_LAZY_EXPORTS = {
    "FilesystemSasrecCheckpointPublisher": (".checkpoint", "FilesystemSasrecCheckpointPublisher"),
    "SasrecCheckpointPublicationPlan": (".checkpoint", "SasrecCheckpointPublicationPlan"),
    "SasrecInitialRanker": (".adapter", "SasrecInitialRanker"),
    "SasrecModel": (".model", "SasrecModel"),
    "SasrecTrainingResult": (".trainer", "SasrecTrainingResult"),
    "build_sasrec_checkpoint_plan": (".checkpoint", "build_sasrec_checkpoint_plan"),
    "load_sasrec_checkpoint_manifest": (".checkpoint", "load_sasrec_checkpoint_manifest"),
    "load_sasrec_checkpoint_payloads": (".checkpoint", "load_sasrec_checkpoint_payloads"),
    "load_sasrec_initial_ranker": (".adapter", "load_sasrec_initial_ranker"),
    "train_initial_ranker_from_config": (".trainer", "train_initial_ranker_from_config"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    import importlib

    module_name, attribute = target
    return getattr(importlib.import_module(module_name, __name__), attribute)


__all__ = [
    "CHECKPOINT_IDENTITY_SCHEMA",
    "CHECKPOINT_SCHEMA",
    "EPOCH_ORDER_RECIPE",
    "NEGATIVE_SAMPLER_RECIPE",
    "CheckpointPayload",
    "CheckpointPublicationResult",
    "FilesystemSasrecCheckpointPublisher",
    "Phase3SasrecTrainingConfig",
    "SasrecCheckpointManifest",
    "SasrecCheckpointPublicationPlan",
    "SasrecInitialRanker",
    "SasrecModel",
    "SasrecModelConfig",
    "SasrecOperationalConfig",
    "SasrecTrainingRecipeConfig",
    "SasrecTrainingResult",
    "build_sasrec_checkpoint_plan",
    "deterministic_uniform_negative",
    "epoch_sample_order",
    "load_phase3_sasrec_training_config",
    "load_sasrec_checkpoint_manifest",
    "load_sasrec_checkpoint_payloads",
    "load_sasrec_initial_ranker",
    "train_initial_ranker_from_config",
]
