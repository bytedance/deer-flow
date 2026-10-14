"""Session test doubles for repository upserts that race a concurrent writer.

A select-then-write upsert loses a race when another writer inserts the same
key between its SELECT and its INSERT. ``MissSelectSession`` reproduces that
deterministically: its first ``misses`` SELECTs report no row even though one
exists, so the repository INSERTs and hits the unique key exactly as the
losing writer would.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class _EmptyResult:
    @staticmethod
    def scalar_one_or_none() -> None:
        return None


class MissSelectSession:
    """Wrap an ``AsyncSession`` so its first ``misses`` ``execute`` calls find no row.

    ``misses=None`` misses every call, which drives a retry loop to
    exhaustion. ``missed`` counts the calls that were made to miss.
    """

    def __init__(self, session: Any, *, misses: int | None = 1) -> None:
        self._session = session
        self._misses = misses
        self.missed = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        result = await self._session.execute(*args, **kwargs)
        if self._misses is None or self.missed < self._misses:
            self.missed += 1
            return _EmptyResult()
        return result

    async def __aenter__(self) -> MissSelectSession:
        await self._session.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> Any:
        return await self._session.__aexit__(*args)


def miss_select_factory(real_factory: Callable[[], Any], *, misses: int | None = 1) -> tuple[Callable[[], MissSelectSession], list[MissSelectSession]]:
    """Return a session factory producing ``MissSelectSession`` wrappers, and the list of sessions it created."""
    sessions: list[MissSelectSession] = []

    def factory() -> MissSelectSession:
        session = MissSelectSession(real_factory(), misses=misses)
        sessions.append(session)
        return session

    return factory, sessions
