"""Strict configuration for Phase 3 full-catalog evaluation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.phase3.config import LoadedPhase3Config, Phase3ConfigBase, load_phase3_config
from pave_rec.preprocessing.paths import require_sha256, validate_filesystem_key, validate_root_id

DEVICE_PATTERN = re.compile(r"^(cpu|cuda:[0-9]+)$")


class Phase3EvaluationConfig(Phase3ConfigBase):
    kind: Literal["phase3-evaluation"]
    derived_artifact_ref: ResourceRef
    method: Literal["mostpop-v1", "sasrec-pytorch-v1"]
    checkpoint_ref: ResourceRef | None
    split: Literal["validation", "test"]
    output_root_id: str
    device: str
    candidate_chunk_size: int
    user_batch_size: int

    @field_validator("output_root_id")
    @classmethod
    def _validate_output(cls, value: str) -> str:
        return validate_root_id(value)

    @field_validator("device")
    @classmethod
    def _validate_device(cls, value: str) -> str:
        if DEVICE_PATTERN.fullmatch(value) is None:
            raise ValueError("evaluation device must be cpu or cuda:<index>")
        return value

    @field_validator("candidate_chunk_size", "user_batch_size")
    @classmethod
    def _validate_chunk(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("evaluation chunk/batch sizes must be positive")
        return value

    @model_validator(mode="after")
    def _validate_graph(self) -> "Phase3EvaluationConfig":
        if (self.method == "sasrec-pytorch-v1") != (self.checkpoint_ref is not None):
            raise ValueError("SASRec evaluation requires one exact checkpoint ref")
        for field_name, ref in (
            ("derived_artifact_ref", self.derived_artifact_ref),
            ("checkpoint_ref", self.checkpoint_ref),
        ):
            if ref is None:
                continue
            validate_filesystem_key(ref.key)
            require_sha256(ref.checksum, f"{field_name}.checksum")
            root = self.storage.roots.get(ref.store)
            if root is None or root.access != "read_only":
                raise ValueError(f"{field_name} must use a declared read_only root")
        output = self.storage.roots.get(self.output_root_id)
        if output is None or output.access != "write_new":
            raise ValueError("output_root_id must use a declared write_new root")
        return self


def load_phase3_evaluation_config(
    config_path: str | Path,
) -> LoadedPhase3Config[Phase3EvaluationConfig]:
    return load_phase3_config(config_path, Phase3EvaluationConfig)
