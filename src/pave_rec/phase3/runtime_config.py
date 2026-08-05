"""Strict zero-budget runtime configuration for the first real Phase 3 Cheap Path."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator

from pave_rec.config import RUN_ID_PATTERN
from pave_rec.domain import ResourceRef
from pave_rec.domain.base import FrozenModel, require_finite, require_non_empty
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key, validate_root_id

from .config import LoadedPhase3Config, Phase3ConfigBase, load_phase3_config

P2_DATA_VERSION_PATTERN = re.compile(r"^p2-[0-9a-f]{64}$")
DEVICE_PATTERN = re.compile(r"^(cpu|cuda:[0-9]+)$")

PHASE3_RUNTIME_DESCRIPTOR_VALUES = {
    "user_memory": ("ArtifactUserMemory", "dynamic-hybrid-memory-v1"),
    "initial_ranker": ("SASRecInitialRanker", "sasrec-pytorch-v1"),
    "item_feature_store": (
        "FilesystemItemFeatureStore",
        "filesystem-item-feature-store-v1",
    ),
    "segment_store": ("FilesystemSegmentStore", "filesystem-segment-store-v1"),
    "state_builder": ("DefaultRecommendationStateBuilder", "phase1-v1"),
    "information_need": (
        "UnavailableInformationNeedEstimator",
        "phase3-zero-budget-v1",
    ),
    "segment_value": ("UnavailableSegmentValueModel", "phase3-zero-budget-v1"),
    "perceiver": ("UnavailableSegmentPerceiver", "phase3-zero-budget-v1"),
    "evidence_updater": ("UnavailableEvidenceUpdater", "phase3-zero-budget-v1"),
    "observation_updater": (
        "UnavailableObservationUpdater",
        "phase3-zero-budget-v1",
    ),
    "score_updater": ("UnavailableScoreUpdater", "phase3-zero-budget-v1"),
    "stop_policy": ("ThresholdStopPolicy", "phase1-v1"),
    "trace_writer": ("JsonlTraceWriter", "phase1-v1"),
}


def _require_exact_ref(ref: ResourceRef, field_name: str) -> ResourceRef:
    validate_root_id(ref.store)
    validate_filesystem_key(ref.key)
    require_sha256(ref.checksum, f"{field_name}.checksum")
    return ref


class Phase3RuntimeRunConfig(FrozenModel):
    output_root_id: str
    run_id: str | None = None

    @field_validator("output_root_id")
    @classmethod
    def _validate_root_id(cls, value: str) -> str:
        return validate_root_id(value)

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str | None) -> str | None:
        if value is not None and RUN_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("run_id must be YYYYMMDDTHHMMSSZ-<8 lowercase hex>")
        return value


class Phase3RuntimeAgentConfig(FrozenModel):
    max_perception_actions: int

    @field_validator("max_perception_actions")
    @classmethod
    def _validate_budget(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_perception_actions must be non-negative")
        return value


class Phase3RuntimeStopConfig(FrozenModel):
    ranking_margin_threshold: None
    min_segment_value: float | None = None

    @field_validator("min_segment_value")
    @classmethod
    def _validate_min_value(cls, value: float | None) -> float | None:
        if value is not None:
            return require_finite(value, "min_segment_value")
        return value


class Phase3RuntimeComponentsConfig(FrozenModel):
    user_memory: Literal["artifact"]
    initial_ranker: Literal["sasrec"]
    item_feature_store: Literal["persistent"]
    segment_store: Literal["persistent"]
    state_builder: Literal["default"]
    information_need: Literal["unavailable"]
    segment_value: Literal["unavailable"]
    perceiver: Literal["unavailable"]
    evidence_updater: Literal["unavailable"]
    observation_updater: Literal["unavailable"]
    score_updater: Literal["unavailable"]
    stop_policy: Literal["threshold"]
    trace_writer: Literal["jsonl"]


class Phase3RuntimeArtifactGraph(FrozenModel):
    p2_release_ref: ResourceRef
    derived_dataset_ref: ResourceRef
    item_semantics_ref: ResourceRef
    sasrec_checkpoint_ref: ResourceRef
    memory_snapshot_ref: ResourceRef
    agent_input_bundle_ref: ResourceRef

    @model_validator(mode="after")
    def _validate_exact_graph(self) -> "Phase3RuntimeArtifactGraph":
        for field_name in self.__class__.model_fields:
            _require_exact_ref(getattr(self, field_name), field_name)
        identities = tuple(
            (getattr(self, field_name).store, getattr(self, field_name).key)
            for field_name in self.__class__.model_fields
        )
        if len(identities) != len(set(identities)):
            raise ValueError("runtime artifact refs must use distinct store/key identities")
        return self


class Phase3RuntimeConfig(Phase3ConfigBase):
    kind: Literal["phase3-runtime"]
    seed: int
    data_version: str
    device: str
    run: Phase3RuntimeRunConfig
    agent: Phase3RuntimeAgentConfig
    stop: Phase3RuntimeStopConfig
    components: Phase3RuntimeComponentsConfig
    artifacts: Phase3RuntimeArtifactGraph

    @field_validator("seed")
    @classmethod
    def _validate_seed(cls, value: int) -> int:
        if value < 0:
            raise ValueError("seed must be non-negative")
        return value

    @field_validator("data_version")
    @classmethod
    def _validate_data_version(cls, value: str) -> str:
        if P2_DATA_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("data_version must be p2-<64 lowercase hex>")
        return value

    @field_validator("device")
    @classmethod
    def _validate_device(cls, value: str) -> str:
        require_non_empty(value, "device")
        if DEVICE_PATTERN.fullmatch(value) is None:
            raise ValueError("device must be cpu or cuda:<non-negative index>")
        return value

    @model_validator(mode="after")
    def _validate_zero_budget_and_root_roles(self) -> "Phase3RuntimeConfig":
        if self.agent.max_perception_actions != 0:
            raise ValueError("unavailable Phase 4/5 components require max_perception_actions=0")
        output_root = self.storage.roots.get(self.run.output_root_id)
        if output_root is None or output_root.access != "write_new":
            raise ValueError("run.output_root_id must reference a declared write_new root")
        for field_name in self.artifacts.__class__.model_fields:
            ref = getattr(self.artifacts, field_name)
            root = self.storage.roots.get(ref.store)
            if root is None or root.access != "read_only":
                raise ValueError(f"{field_name} must reference a declared read_only root")
        return self


def load_phase3_runtime_config(
    config_path: str | Path,
) -> LoadedPhase3Config[Phase3RuntimeConfig]:
    return load_phase3_config(config_path, Phase3RuntimeConfig)
