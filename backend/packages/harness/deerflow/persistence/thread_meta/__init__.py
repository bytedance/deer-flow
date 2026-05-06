"""Thread metadata persistence — ORM, abstract store, and concrete implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deerflow.persistence.thread_meta.base import ThreadMetaStore
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = [
    "MemoryThreadMetaStore",
    "ThreadMetaRepository",
    "ThreadMetaRow",
    "ThreadMetaStore",
    "make_thread_store",
]


def make_thread_store(
    session_factory: async_sessionmaker[AsyncSession] | None,
    store: BaseStore | None = None,
) -> ThreadMetaStore:
    """Create the appropriate ThreadMetaStore based on available backends.

    Returns a SQL-backed repository when a session factory is available,
    otherwise falls back to the in-memory LangGraph Store implementation.
    """
    if session_factory is not None:
        return ThreadMetaRepository(session_factory)
    if store is None:
        raise ValueError("make_thread_store requires either a session_factory (SQL) or a store (memory)")
    return MemoryThreadMetaStore(store)
