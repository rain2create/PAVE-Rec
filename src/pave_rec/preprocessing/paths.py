"""Trusted storage-root registry and filesystem key containment rules."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Literal, Mapping

from pave_rec.domain import ResourceRef
from pave_rec.errors import ConfigurationError, ResourceResolutionError

SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
ROOT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def require_sha256(checksum: str | None, field_name: str = "checksum") -> str:
    if checksum is None or SHA256_PATTERN.fullmatch(checksum) is None:
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
    return checksum


def validate_root_id(root_id: str) -> str:
    if ROOT_ID_PATTERN.fullmatch(root_id) is None:
        raise ValueError("root ID must be a portable lowercase identifier")
    return root_id


def validate_filesystem_key(key: str) -> str:
    """Validate one portable relative POSIX key without normalizing it."""

    if not key:
        raise ValueError("filesystem key must not be empty")
    if key != unicodedata.normalize("NFC", key):
        raise ValueError("filesystem key must use NFC Unicode normalization")
    if "\\" in key:
        raise ValueError("filesystem key must use POSIX separators")
    if PurePosixPath(key).is_absolute() or PureWindowsPath(key).anchor:
        raise ValueError("filesystem key must be relative under all supported path grammars")
    if any(ord(character) < 32 or ord(character) == 127 for character in key):
        raise ValueError("filesystem key contains a control character")
    parts = key.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("filesystem key contains an empty or dot path segment")
    for part in parts:
        if part.endswith((" ", ".")):
            raise ValueError("filesystem key component has an ambiguous trailing character")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise ValueError("filesystem key contains a Windows-reserved component")
    return key


def validate_case_collisions(keys: tuple[str, ...]) -> tuple[str, ...]:
    folded: dict[str, str] = {}
    for key in keys:
        validate_filesystem_key(key)
        normalized = key.casefold()
        previous = folded.get(normalized)
        if previous is not None and previous != key:
            raise ValueError(f"filesystem keys collide case-insensitively: {previous!r}, {key!r}")
        folded[normalized] = key
    return keys


def validate_resource_ref_collisions(refs: tuple[ResourceRef, ...]) -> tuple[ResourceRef, ...]:
    """Reject case-insensitive key collisions independently inside each storage root."""

    keys_by_root: dict[str, list[str]] = {}
    for ref in refs:
        keys_by_root.setdefault(ref.store, []).append(ref.key)
    for keys in keys_by_root.values():
        validate_case_collisions(tuple(keys))
    return refs


@dataclass(frozen=True)
class ResolvedStorageRoot:
    root_id: str
    configured_path: str
    path: Path
    access: Literal["read_only", "write_new"]


class RootRegistry:
    """Immutable trusted binding from portable root IDs to resolved local directories."""

    def __init__(self, roots: Mapping[str, ResolvedStorageRoot]) -> None:
        self._roots = MappingProxyType(dict(roots))

    @property
    def roots(self) -> Mapping[str, ResolvedStorageRoot]:
        return self._roots

    def require(self, root_id: str) -> ResolvedStorageRoot:
        try:
            return self._roots[root_id]
        except KeyError as exc:
            raise ResourceResolutionError(f"unknown storage root: {root_id}") from exc


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def build_root_registry(
    declarations: Mapping[str, tuple[str, Literal["read_only", "write_new"]]],
    *,
    project_root: Path,
) -> RootRegistry:
    roots: dict[str, ResolvedStorageRoot] = {}
    for root_id, (configured_path, access) in declarations.items():
        try:
            validate_root_id(root_id)
        except ValueError as exc:
            raise ConfigurationError(f"invalid storage root ID {root_id!r}: {exc}") from exc
        requested = Path(configured_path)
        candidate = requested if requested.is_absolute() else project_root / requested
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise ConfigurationError(f"storage root does not exist: {root_id}") from exc
        if not resolved.is_dir():
            raise ConfigurationError(f"storage root is not a directory: {root_id}")
        roots[root_id] = ResolvedStorageRoot(
            root_id=root_id,
            configured_path=configured_path,
            path=resolved,
            access=access,
        )
    entries = tuple(roots.values())
    for index, left in enumerate(entries):
        for right in entries[index + 1 :]:
            if _inside(left.path, right.path) or _inside(right.path, left.path):
                raise ConfigurationError(
                    f"storage roots must not overlap: {left.root_id}, {right.root_id}"
                )
    return RootRegistry(roots)


class FilesystemPathResolver:
    """Path-safety core shared by source ingestion and release-scoped resolution."""

    def __init__(self, registry: RootRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> RootRegistry:
        return self._registry

    def _safe_parts(self, key: str) -> tuple[str, ...]:
        try:
            validate_filesystem_key(key)
        except ValueError as exc:
            raise ResourceResolutionError(f"unsafe filesystem key: {exc}") from exc
        return tuple(key.split("/"))

    def resolve_read_path(self, ref: ResourceRef) -> Path:
        root = self._registry.require(ref.store)
        parts = self._safe_parts(ref.key)
        try:
            resolved = root.path.joinpath(*parts).resolve(strict=True)
        except OSError as exc:
            raise ResourceResolutionError(
                f"resource does not exist: {ref.store}/{ref.key}"
            ) from exc
        if not _inside(resolved, root.path) or not resolved.is_file():
            raise ResourceResolutionError(
                f"resource is not a contained file: {ref.store}/{ref.key}"
            )
        return resolved

    def resolve_new_path(self, root_id: str, key: str) -> Path:
        root = self._registry.require(root_id)
        if root.access != "write_new":
            raise ResourceResolutionError(f"storage root is not writable: {root_id}")
        parts = self._safe_parts(key)
        target = root.path.joinpath(*parts)
        existing = target.parent
        while not existing.exists() and existing != root.path:
            existing = existing.parent
        try:
            resolved_parent = existing.resolve(strict=True)
        except OSError as exc:
            raise ResourceResolutionError(
                f"cannot resolve output parent for {root_id}/{key}"
            ) from exc
        if not _inside(resolved_parent, root.path):
            raise ResourceResolutionError(f"output path escapes storage root: {root_id}/{key}")
        return target

    def read_verified_bytes(
        self,
        ref: ResourceRef,
        *,
        expected_size: int | None = None,
    ) -> bytes:
        try:
            checksum = require_sha256(ref.checksum)
        except ValueError as exc:
            raise ResourceResolutionError(str(exc)) from exc
        path = self.resolve_read_path(ref)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ResourceResolutionError(f"cannot read resource: {ref.store}/{ref.key}") from exc
        if expected_size is not None and len(payload) != expected_size:
            raise ResourceResolutionError(f"resource size mismatch: {ref.store}/{ref.key}")
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if digest != checksum:
            raise ResourceResolutionError(f"resource checksum mismatch: {ref.store}/{ref.key}")
        return payload
