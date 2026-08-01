"""Fixture-backed user-memory implementation for Phase 1."""

from pave_rec.domain import ComponentDescriptor, UserMemoryView
from pave_rec.errors import ContractError
from pave_rec.fixture import MockFixture


class MockUserMemory:
    descriptor = ComponentDescriptor(
        role="user_memory", implementation="MockUserMemory", version="mock-v1"
    )

    def __init__(self, fixture: MockFixture) -> None:
        self._fixture = fixture

    def build_or_update(self, user_id: str, history: tuple[str, ...]) -> UserMemoryView:
        if user_id != self._fixture.input.user_id or history != self._fixture.input.history:
            raise ContractError("unknown MockUserMemory fixture key")
        return self._fixture.user_memory
