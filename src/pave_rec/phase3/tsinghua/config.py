"""Strict local lifecycle config for the pinned Tsinghua source adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator

from pave_rec.phase3.config import LoadedPhase3Config, Phase3ConfigBase, load_phase3_config
from pave_rec.preprocessing.paths import validate_root_id

from .models import TsinghuaSnapshotIdentity


class TsinghuaSourceAdapterConfig(Phase3ConfigBase):
    kind: Literal["tsinghua-source-adapter"]
    source_root_id: str
    output_root_id: str
    snapshot: TsinghuaSnapshotIdentity

    @field_validator("source_root_id", "output_root_id")
    @classmethod
    def _validate_root_id(cls, value: str) -> str:
        return validate_root_id(value)

    @model_validator(mode="after")
    def _validate_root_roles(self) -> "TsinghuaSourceAdapterConfig":
        source = self.storage.roots.get(self.source_root_id)
        output = self.storage.roots.get(self.output_root_id)
        if source is None or source.access != "read_only":
            raise ValueError("source_root_id must reference a declared read_only root")
        if output is None or output.access != "write_new":
            raise ValueError("output_root_id must reference a declared write_new root")
        if self.source_root_id == self.output_root_id:
            raise ValueError("source and output roots must be distinct")
        return self


def load_tsinghua_source_adapter_config(
    config_path: str | Path,
) -> LoadedPhase3Config[TsinghuaSourceAdapterConfig]:
    return load_phase3_config(config_path, TsinghuaSourceAdapterConfig)
