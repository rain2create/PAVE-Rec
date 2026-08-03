"""Canonical Phase 2 JSON/JSONL encoding and strict typed decoding."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from pave_rec.domain.serialization import canonical_json_bytes
from pave_rec.errors import DatasetValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


def encode_json(value: BaseModel) -> bytes:
    return canonical_json_bytes(value, pretty=True)


def encode_jsonl(values: tuple[BaseModel, ...]) -> bytes:
    return b"".join(canonical_json_bytes(value, pretty=False) for value in values)


def decode_json(payload: bytes, model_type: type[ModelT], *, logical_name: str) -> ModelT:
    try:
        return model_type.model_validate_json(payload)
    except ValidationError as exc:
        raise DatasetValidationError(f"invalid {logical_name}: {exc}") from exc


def decode_jsonl(
    payload: bytes,
    model_type: type[ModelT],
    *,
    logical_name: str,
) -> tuple[ModelT, ...]:
    if not payload:
        return ()
    lines = payload.splitlines()
    values: list[ModelT] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise DatasetValidationError(f"invalid {logical_name} line {line_number}: blank line")
        try:
            values.append(model_type.model_validate_json(line))
        except ValidationError as exc:
            raise DatasetValidationError(
                f"invalid {logical_name} line {line_number}: {exc}"
            ) from exc
    return tuple(values)


def decode_canonical_json(
    payload: bytes,
    model_type: type[ModelT],
    *,
    logical_name: str,
    pretty: bool = True,
) -> ModelT:
    value = decode_json(payload, model_type, logical_name=logical_name)
    if canonical_json_bytes(value, pretty=pretty) != payload:
        raise DatasetValidationError(f"{logical_name} does not use canonical JSON bytes")
    return value
