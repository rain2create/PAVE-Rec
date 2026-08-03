"""Release-scoped verified filesystem resource resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pave_rec.domain import ResourceRef
from pave_rec.errors import ResourceResolutionError
from pave_rec.preprocessing.paths import FilesystemPathResolver

from .release import LoadedRelease, resource_identity


class ResourceResolver(Protocol):
    def read_verified_bytes(self, ref: ResourceRef) -> bytes: ...

    def resolve_verified_path(self, ref: ResourceRef) -> Path: ...


class FilesystemResourceResolver:
    def __init__(self, loaded_release: LoadedRelease) -> None:
        self._loaded_release = loaded_release
        self._paths = FilesystemPathResolver(loaded_release.root_registry)

    @property
    def loaded_release(self) -> LoadedRelease:
        return self._loaded_release

    def _entry(self, ref: ResourceRef):
        try:
            return self._loaded_release.inventory[resource_identity(ref)]
        except KeyError as exc:
            raise ResourceResolutionError(
                f"resource is outside loaded release: {ref.store}/{ref.key}"
            ) from exc

    def read_verified_bytes(self, ref: ResourceRef) -> bytes:
        entry = self._entry(ref)
        return self._paths.read_verified_bytes(ref, expected_size=entry.size_bytes)

    def resolve_verified_path(self, ref: ResourceRef) -> Path:
        self.read_verified_bytes(ref)
        return self._paths.resolve_read_path(ref)
