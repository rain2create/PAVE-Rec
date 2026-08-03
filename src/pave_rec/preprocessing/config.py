"""Independent deterministic configuration loading for Phase 2 preprocessing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

import yaml
from pydantic import ValidationError, field_validator, model_validator

from pave_rec.domain import ResourceRef
from pave_rec.domain.base import FrozenModel, require_non_empty
from pave_rec.errors import ConfigurationError

from .paths import RootRegistry, build_root_registry, require_sha256, validate_root_id


class StorageRootConfig(FrozenModel):
    path: str
    access: Literal["read_only", "write_new"]

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return require_non_empty(value, "path")


class SourceConfig(FrozenModel):
    manifest_ref: ResourceRef

    @model_validator(mode="after")
    def _validate_manifest_ref(self) -> "SourceConfig":
        require_sha256(self.manifest_ref.checksum, "source.manifest_ref.checksum")
        return self


class StorageConfig(FrozenModel):
    roots: dict[str, StorageRootConfig]

    @model_validator(mode="after")
    def _validate_roots(self) -> "StorageConfig":
        if not self.roots:
            raise ValueError("storage.roots must not be empty")
        for root_id in self.roots:
            validate_root_id(root_id)
        return self


class OutputConfig(FrozenModel):
    processed_root_id: str
    features_root_id: str

    @field_validator("processed_root_id", "features_root_id")
    @classmethod
    def _validate_root_ids(cls, value: str) -> str:
        validate_root_id(value)
        return value

    @model_validator(mode="after")
    def _validate_distinct(self) -> "OutputConfig":
        if self.processed_root_id == self.features_root_id:
            raise ValueError("processed and features roots must be different")
        return self


AttributeValueType = Literal[
    "string",
    "integer",
    "number",
    "boolean",
    "string_list",
    "integer_list",
    "number_list",
]


class AttributeMapping(FrozenModel):
    source_key: str
    output_key: str
    value_type: AttributeValueType
    required: bool

    @field_validator("source_key", "output_key")
    @classmethod
    def _validate_keys(cls, value: str, info: Any) -> str:
        return require_non_empty(value, info.field_name)


def _validate_mappings(
    mappings: tuple[AttributeMapping, ...], label: str
) -> tuple[AttributeMapping, ...]:
    source_keys = tuple(entry.source_key for entry in mappings)
    output_keys = tuple(entry.output_key for entry in mappings)
    if len(source_keys) != len(set(source_keys)) or len(output_keys) != len(set(output_keys)):
        raise ValueError(f"{label} mappings require unique source/output keys")
    if output_keys != tuple(sorted(output_keys)):
        raise ValueError(f"{label} mappings must be sorted by output_key")
    return mappings


class FeatureConfig(FrozenModel):
    item_attributes: tuple[AttributeMapping, ...]
    segment_attributes: tuple[AttributeMapping, ...]

    @field_validator("item_attributes", "segment_attributes", mode="before")
    @classmethod
    def _parse_yaml_lists(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def _validate_mapping_order(self) -> "FeatureConfig":
        _validate_mappings(self.item_attributes, "item")
        _validate_mappings(self.segment_attributes, "segment")
        return self


class CodecConfig(FrozenModel):
    source_manifest: Literal["canonical-json-v1"]
    source_records: Literal["canonical-jsonl-v1"]
    behavior_sequences: Literal["canonical-jsonl-v1"]
    feature_records: Literal["canonical-json-v1"]
    manifests_and_indexes: Literal["canonical-json-v1"]
    compression: Literal["none"]


class PreprocessingComponentConfig(FrozenModel):
    behavior_processor: Literal["canonical"]
    segment_definition_provider: Literal["manifest"]
    item_feature_extractor: Literal["structural"]
    segment_proxy_extractor: Literal["structural"]


class LimitConfig(FrozenModel):
    max_items: int
    max_behavior_events: int
    max_total_segments: int
    max_segments_per_item: int

    @field_validator(
        "max_items",
        "max_behavior_events",
        "max_total_segments",
        "max_segments_per_item",
    )
    @classmethod
    def _validate_positive(cls, value: int, info: Any) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return value


class Phase2PreprocessingConfig(FrozenModel):
    schema_version: Literal["1"]
    source: SourceConfig
    storage: StorageConfig
    output: OutputConfig
    codecs: CodecConfig
    features: FeatureConfig
    components: PreprocessingComponentConfig
    limits: LimitConfig

    @model_validator(mode="after")
    def _validate_root_roles(self) -> "Phase2PreprocessingConfig":
        roots = self.storage.roots
        source_root = roots.get(self.source.manifest_ref.store)
        if source_root is None or source_root.access != "read_only":
            raise ValueError("source manifest must reference a declared read_only root")
        for root_id in (self.output.processed_root_id, self.output.features_root_id):
            root = roots.get(root_id)
            if root is None or root.access != "write_new":
                raise ValueError("output root IDs must reference declared write_new roots")
        return self


@dataclass(frozen=True)
class LoadedPreprocessingConfig:
    config: Phase2PreprocessingConfig
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
        raise ConfigurationError(f"cannot read YAML config {path.name}: {exc}") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ConfigurationError(f"config {path.name} must contain a string-keyed mapping")
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
        raise ConfigurationError("extends chain escapes the project root")
    if resolved in active:
        cycle = " -> ".join(entry.name for entry in (*active, resolved))
        raise ConfigurationError(f"config inheritance cycle detected: {cycle}")
    payload = _read_yaml(resolved)
    extends = payload.pop("extends", None)
    if extends is None:
        return payload
    if not isinstance(extends, str) or not extends.strip() or _has_platform_anchor(extends):
        raise ConfigurationError("extends must be one non-empty relative path")
    try:
        parent = _load_chain(resolved.parent / extends, root, (*active, resolved))
    except OSError as exc:
        raise ConfigurationError(f"cannot resolve config inheritance: {exc}") from exc
    return _merge(parent, payload)


def load_preprocessing_config(config_path: str | Path) -> LoadedPreprocessingConfig:
    requested = Path(config_path)
    try:
        resolved_path = requested.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"config does not exist: {requested}") from exc
    if not resolved_path.is_file():
        raise ConfigurationError(f"config is not a file: {requested}")
    project_root = _find_project_root(resolved_path)
    try:
        merged = _load_chain(resolved_path, project_root, ())
        config = Phase2PreprocessingConfig.model_validate(merged)
        declarations = {
            root_id: (root.path, root.access) for root_id, root in config.storage.roots.items()
        }
        registry = build_root_registry(declarations, project_root=project_root)
    except (ValidationError, ValueError) as exc:
        raise ConfigurationError(f"invalid Phase 2 preprocessing config: {exc}") from exc
    return LoadedPreprocessingConfig(
        config=config,
        project_root=project_root,
        config_path=resolved_path,
        root_registry=registry,
    )
