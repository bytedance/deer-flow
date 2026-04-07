"""Abstract interface for thread metadata storage.

Implementations:
- ThreadMetaRepository: SQL-backed (sqlite / postgres via SQLAlchemy)
- MemoryThreadMetaStore: wraps LangGraph BaseStore (memory mode)
"""

from __future__ import annotations

import abc


class ThreadMetaStore(abc.ABC):
    @abc.abstractmethod
    async def create(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        owner_id: str | None = None,
        display_name: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        pass

    @abc.abstractmethod
    async def get(self, thread_id: str) -> dict | None:
        pass

    @abc.abstractmethod
    async def search(
        self,
        *,
        metadata: dict | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        pass

    @abc.abstractmethod
    async def update_display_name(self, thread_id: str, display_name: str) -> None:
        pass

    @abc.abstractmethod
    async def update_status(self, thread_id: str, status: str) -> None:
        pass

    @abc.abstractmethod
    async def update_metadata(self, thread_id: str, metadata: dict) -> None:
        """Merge ``metadata`` into the thread's metadata field.

        Existing keys are overwritten by the new values; keys absent from
        ``metadata`` are preserved. No-op if the thread does not exist.
        """
        pass

    @abc.abstractmethod
    async def delete(self, thread_id: str) -> None:
        pass
