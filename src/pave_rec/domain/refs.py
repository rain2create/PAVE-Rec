"""Versioned references to resources that stay outside public JSON state."""

from pydantic import ValidationInfo, field_validator

from .base import FrozenModel, require_non_empty, require_optional_non_empty


class ResourceRef(FrozenModel):
    store: str
    key: str
    version: str
    checksum: str | None = None

    @field_validator("store", "key", "version")
    @classmethod
    def _validate_required_strings(cls, value: str, info: ValidationInfo) -> str:
        return require_non_empty(value, info.field_name)

    @field_validator("checksum")
    @classmethod
    def _validate_checksum(cls, value: str | None) -> str | None:
        return require_optional_non_empty(value, "checksum")
