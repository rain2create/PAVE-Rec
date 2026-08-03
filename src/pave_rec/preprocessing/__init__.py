"""Offline data and feature preprocessing pipelines.

Public entry points are loaded lazily so low-level codec and model imports do not
pull the high-level runner (and the Phase 1 controller graph) into package import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import LoadedPreprocessingConfig, Phase2PreprocessingConfig
    from .models import PreprocessingResult

__all__ = [
    "LoadedPreprocessingConfig",
    "Phase2PreprocessingConfig",
    "PreprocessingResult",
    "load_preprocessing_config",
    "preprocess_from_config",
]


def __getattr__(name: str) -> Any:
    if name in {
        "LoadedPreprocessingConfig",
        "Phase2PreprocessingConfig",
        "load_preprocessing_config",
    }:
        from . import config

        return getattr(config, name)
    if name == "PreprocessingResult":
        from .models import PreprocessingResult

        return PreprocessingResult
    if name == "preprocess_from_config":
        from .runner import preprocess_from_config

        return preprocess_from_config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
