"""Shared strict configuration foundation for independent Phase 3 lifecycles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Generic, Literal, TypeVar

import yaml
from pydantic import ValidationError, field_validator, model_validator

from pave_rec.domain.base import FrozenModel, require_non_empty
from pave_rec.errors import ConfigurationError
from pave_rec.preprocessing.paths import RootRegistry, build_root_registry, validate_root_id

Phase3ConfigKind = Literal[
    "tsinghua-source-adapter",
    "phase3-derived-sequences",
    "phase3-item-semantics",
    "phase3-sasrec-training",
    "phase3-memory",
    "phase3-runtime",
    "phase3-evaluation",
    "phase3-memory-audit",
]


class Phase3StorageRootConfig(FrozenModel):
    path: str
    access: Literal["read_only", "write_new"]

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return require_non_empty(value, "path")


class Phase3StorageConfig(FrozenModel):
    roots: dict[str, Phase3StorageRootConfig]

    @model_validator(mode="after")
    def _validate_roots(self) -> "Phase3StorageConfig":
        if not self.roots:
            raise ValueError("storage.roots must not be empty")
        for root_id in self.roots:
            validate_root_id(root_id)
        return self


class Phase3ConfigBase(FrozenModel):
    schema_version: Literal["1"]
    kind: Phase3ConfigKind
    storage: Phase3StorageConfig


ConfigT = TypeVar("ConfigT", bound=Phase3ConfigBase)


@dataclass(frozen=True)
class LoadedPhase3Config(Generic[ConfigT]):
    config: ConfigT
    project_root: Path
    config_path: Path
    root_registry: RootRegistry


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _has_platform_anchor(raw_path: str) -> bool:
    return PurePosixPath(raw_path).is_absolute() or bool(PureWindowsPath(raw_path).anchor)


def _find_project_root(config_path: Path) -> Path:
    for candidate in (config_path.parent, *config_path.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate.resolve()
    raise ConfigurationError("no project root containing pyproject.toml was found")


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"cannot read Phase 3 YAML config {path.name}: {exc}") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ConfigurationError(f"Phase 3 config {path.name} must contain a string-keyed mapping")
    return raw


def _merge(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    merged = dict(parent)
    for key, value in child.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_chain(path: Path, root: Path, active: tuple[Path, ...]) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not _inside(resolved, root):
        raise ConfigurationError("Phase 3 extends chain escapes the project root")
    if resolved in active:
        cycle = " -> ".join(entry.name for entry in (*active, resolved))
        raise ConfigurationError(f"Phase 3 config inheritance cycle detected: {cycle}")
    payload = _read_yaml(resolved)
    extends = payload.pop("extends", None)
    if extends is None:
        return payload
    if not isinstance(extends, str) or not extends.strip() or _has_platform_anchor(extends):
        raise ConfigurationError("Phase 3 extends must be one non-empty relative path")
    try:
        parent = _load_chain(resolved.parent / extends, root, (*active, resolved))
    except OSError as exc:
        raise ConfigurationError(f"cannot resolve Phase 3 config inheritance: {exc}") from exc
    return _merge(parent, payload)


def load_phase3_config(
    config_path: str | Path,
    model_type: type[ConfigT],
) -> LoadedPhase3Config[ConfigT]:
    """Load one lifecycle-specific model with shared inheritance and root rules."""

    requested = Path(config_path)
    try:
        resolved_path = requested.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"Phase 3 config does not exist: {requested}") from exc
    if not resolved_path.is_file():
        raise ConfigurationError(f"Phase 3 config is not a file: {requested}")
    project_root = _find_project_root(resolved_path)
    try:
        merged = _load_chain(resolved_path, project_root, ())
        config = model_type.model_validate(merged)
        declarations = {
            root_id: (root.path, root.access) for root_id, root in config.storage.roots.items()
        }
        registry = build_root_registry(declarations, project_root=project_root)
    except (ValidationError, ValueError) as exc:
        raise ConfigurationError(f"invalid Phase 3 config: {exc}") from exc
    return LoadedPhase3Config(
        config=config,
        project_root=project_root,
        config_path=resolved_path,
        root_registry=registry,
    )
