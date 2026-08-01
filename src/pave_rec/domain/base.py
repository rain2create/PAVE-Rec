"""Base model and validation helpers shared by public domain objects."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, JsonValue


def _copy_json_object(value: Any) -> Any:
    return deepcopy(value)


JsonObject = Annotated[dict[str, JsonValue], BeforeValidator(_copy_json_object)]


class FrozenModel(BaseModel):
    """Strict, shallow-frozen model with defensive copying of input containers."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )


def require_non_empty(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def require_optional_non_empty(value: str | None, field_name: str) -> str | None:
    if value is not None:
        require_non_empty(value, field_name)
    return value


def require_finite(value: float, field_name: str) -> float:
    if not isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    return value


def require_range(value: float, field_name: str, lower: float, upper: float) -> float:
    require_finite(value, field_name)
    if not lower <= value <= upper:
        raise ValueError(f"{field_name} must be in [{lower}, {upper}]")
    return value


T = TypeVar("T")


def require_unique(values: tuple[T, ...], field_name: str) -> tuple[T, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values
