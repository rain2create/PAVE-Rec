"""Read-only exact-snapshot adapter for the unchanged UserMemory protocol."""

from __future__ import annotations

from pave_rec.domain import ComponentDescriptor, UserMemoryView
from pave_rec.errors import ContractError
from pave_rec.phase3.input_bundle import history_prefix_checksum

from .artifact import LoadedMemoryArtifact, resolve_memory_view


class ArtifactUserMemory:
    descriptor = ComponentDescriptor(
        role="user_memory",
        implementation="ArtifactUserMemory",
        version="dynamic-hybrid-memory-v1",
    )

    def __init__(
        self,
        loaded: LoadedMemoryArtifact,
        *,
        bound_user_id: str,
        bound_cutoff_identity: str,
        bound_history_projection_checksum: str,
    ) -> None:
        self._bound_user_id = bound_user_id
        self._bound_cutoff_identity = bound_cutoff_identity
        self._bound_history_projection_checksum = bound_history_projection_checksum
        self._view = resolve_memory_view(
            loaded,
            user_id=bound_user_id,
            cutoff_identity=bound_cutoff_identity,
            history_projection_checksum=bound_history_projection_checksum,
        )

    def build_or_update(self, user_id: str, history: tuple[str, ...]) -> UserMemoryView:
        if user_id != self._bound_user_id:
            raise ContractError("user does not match the bound memory snapshot")
        actual = history_prefix_checksum(user_id, history)
        if actual != self._bound_history_projection_checksum:
            raise ContractError("history does not match the bound memory snapshot")
        return self._view
