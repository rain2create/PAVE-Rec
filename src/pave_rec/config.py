"""Deterministic single-parent configuration loading for Phase 1."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

import yaml
from pydantic import ValidationError, field_validator

from .domain.base import FrozenModel, require_finite, require_non_empty
from .errors import ConfigurationError, RunInputError

SCHEMA_VERSION = "1"
CANONICAL_GOLDEN_RUN_ID = "mock-v1-golden"
RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")

COMPONENT_ROLE_ORDER = (
    "user_memory",
    "initial_ranker",
    "item_feature_store",
    "segment_store",
    "state_builder",
    "information_need",
    "segment_value",
    "perceiver",
    "evidence_updater",
    "observation_updater",
    "score_updater",
    "stop_policy",
    "trace_writer",
)


class RunConfig(FrozenModel):
    output_root: str
    run_id: str | None = None

    @field_validator("output_root")
    @classmethod
    def _validate_output_root(cls, value: str) -> str:
        return require_non_empty(value, "output_root")

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str | None) -> str | None:
        if value is not None:
            validate_run_id(value)
        return value


class AgentConfig(FrozenModel):
    max_perception_actions: int

    @field_validator("max_perception_actions")
    @classmethod
    def _validate_budget(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_perception_actions must be non-negative")
        return value


class StopConfig(FrozenModel):
    ranking_margin_threshold: float | None = None
    min_segment_value: float | None = None

    @field_validator("ranking_margin_threshold")
    @classmethod
    def _validate_margin(cls, value: float | None) -> float | None:
        if value is not None:
            require_finite(value, "ranking_margin_threshold")
            if value < 0:
                raise ValueError("ranking_margin_threshold must be non-negative")
        return value

    @field_validator("min_segment_value")
    @classmethod
    def _validate_min_value(cls, value: float | None) -> float | None:
        if value is not None:
            return require_finite(value, "min_segment_value")
        return value


class ComponentsConfig(FrozenModel):
    user_memory: Literal["mock"]
    initial_ranker: Literal["mock"]
    item_feature_store: Literal["in_memory"]
    segment_store: Literal["in_memory"]
    state_builder: Literal["default"]
    information_need: Literal["mock"]
    segment_value: Literal["mock"]
    perceiver: Literal["mock"]
    evidence_updater: Literal["mock"]
    observation_updater: Literal["mock"]
    score_updater: Literal["mock"]
    stop_policy: Literal["threshold"]
    trace_writer: Literal["jsonl"]

    def ordered_items(self) -> tuple[tuple[str, str], ...]:
        return tuple((role, getattr(self, role)) for role in COMPONENT_ROLE_ORDER)


class InputConfig(FrozenModel):
    fixture_path: str

    @field_validator("fixture_path")
    @classmethod
    def _validate_fixture_path(cls, value: str) -> str:
        return require_non_empty(value, "fixture_path")


class Phase1Config(FrozenModel):
    schema_version: Literal["1"]
    seed: int
    data_version: str
    run: RunConfig
    agent: AgentConfig
    stop: StopConfig
    components: ComponentsConfig
    input: InputConfig

    @field_validator("seed")
    @classmethod
    def _validate_seed(cls, value: int) -> int:
        if value < 0:
            raise ValueError("seed must be non-negative")
        return value

    @field_validator("data_version")
    @classmethod
    def _validate_data_version(cls, value: str) -> str:
        return require_non_empty(value, "data_version")


@dataclass(frozen=True)
class LoadedConfig:
    config: Phase1Config
    project_root: Path
    config_path: Path


def validate_run_id(run_id: str) -> str:
    require_non_empty(run_id, "run_id")
    if run_id != CANONICAL_GOLDEN_RUN_ID and RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run_id must be mock-v1-golden or YYYYMMDDTHHMMSSZ-<8 lowercase hex>")
    return run_id


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _has_platform_anchor(raw_path: str) -> bool:
    """Reject paths anchored under either supported host path grammar."""

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
    if not isinstance(raw, dict):
        raise ConfigurationError(f"config {path.name} must contain a YAML mapping")
    if not all(isinstance(key, str) for key in raw):
        raise ConfigurationError(f"config {path.name} must use string keys")
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
    if not isinstance(extends, str) or not extends.strip():
        raise ConfigurationError("extends must be one non-empty relative path")
    extends_path = Path(extends)
    if _has_platform_anchor(extends):
        raise ConfigurationError("extends must be relative to the declaring config")
    try:
        parent = _load_chain(resolved.parent / extends_path, root, (*active, resolved))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"extended config does not exist: {extends}") from exc
    return _merge(parent, payload)


def _normalize_project_path(raw_path: Any, root: Path, field_name: str) -> str:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ConfigurationError(f"{field_name} must be a non-empty relative path")
    path = Path(raw_path)
    if _has_platform_anchor(raw_path):
        raise ConfigurationError(f"{field_name} must be project-relative")
    resolved = (root / path).resolve(strict=False)
    if not _inside(resolved, root):
        raise ConfigurationError(f"{field_name} escapes the project root")
    relative = resolved.relative_to(root).as_posix()
    if relative == ".":
        raise ConfigurationError(f"{field_name} cannot be the project root")
    return relative


def load_config(config_path: str | Path) -> LoadedConfig:
    """Load, inherit, normalize, and strictly validate one Phase 1 config."""

    requested = Path(config_path)
    try:
        resolved_config_path = requested.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"config does not exist: {requested}") from exc
    if not resolved_config_path.is_file():
        raise ConfigurationError(f"config is not a file: {requested}")
    project_root = _find_project_root(resolved_config_path)
    try:
        merged = _load_chain(resolved_config_path, project_root, ())
    except OSError as exc:
        raise ConfigurationError(f"cannot resolve config inheritance: {exc}") from exc

    run = merged.get("run")
    input_config = merged.get("input")
    if not isinstance(run, dict) or not isinstance(input_config, dict):
        raise ConfigurationError("merged config requires run and input mappings")
    run["output_root"] = _normalize_project_path(
        run.get("output_root"), project_root, "run.output_root"
    )
    input_config["fixture_path"] = _normalize_project_path(
        input_config.get("fixture_path"), project_root, "input.fixture_path"
    )
    try:
        config = Phase1Config.model_validate(merged)
    except (ValidationError, ValueError) as exc:
        raise ConfigurationError(f"invalid Phase 1 config: {exc}") from exc
    return LoadedConfig(config=config, project_root=project_root, config_path=resolved_config_path)


def with_actual_run_id(config: Phase1Config, run_id: str) -> Phase1Config:
    try:
        validate_run_id(run_id)
        payload = config.model_dump(mode="python", exclude_none=False)
        payload["run"]["run_id"] = run_id
        return Phase1Config.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise RunInputError(f"invalid run ID: {exc}") from exc
