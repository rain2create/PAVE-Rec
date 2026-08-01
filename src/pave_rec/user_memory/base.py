"""User-memory component protocol."""

from typing import Protocol

from pave_rec.domain import ComponentDescriptor, UserMemoryView


class UserMemory(Protocol):
    @property
    def descriptor(self) -> ComponentDescriptor: ...

    def build_or_update(self, user_id: str, history: tuple[str, ...]) -> UserMemoryView: ...
