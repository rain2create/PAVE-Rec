"""Item, segment, feature, and memory storage adapters.

Filesystem implementations are lazy imports so importing the Phase 1 Store
interfaces does not initialize the complete persistent data plane.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .filesystem import FilesystemItemFeatureStore, FilesystemSegmentStore
    from .release import LoadedRelease, ReleaseLoader
    from .resolver import FilesystemResourceResolver, ResourceResolver

__all__ = [
    "FilesystemItemFeatureStore",
    "FilesystemResourceResolver",
    "FilesystemSegmentStore",
    "LoadedRelease",
    "ReleaseLoader",
    "ResourceResolver",
]


def __getattr__(name: str) -> Any:
    if name in {"FilesystemItemFeatureStore", "FilesystemSegmentStore"}:
        from . import filesystem

        return getattr(filesystem, name)
    if name in {"LoadedRelease", "ReleaseLoader"}:
        from . import release

        return getattr(release, name)
    if name in {"FilesystemResourceResolver", "ResourceResolver"}:
        from . import resolver

        return getattr(resolver, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
