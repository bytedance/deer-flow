"""Owner-bound workspace search contributions. No framework or storage dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchThread:
    thread_id: str
    incarnation: str
    title: str
    updated_at: str
    agent_name: str | None = None
    project_id: str | None = None
    archived: bool = False


@dataclass(frozen=True)
class SearchMessage:
    thread_id: str
    incarnation: str
    message_id: str
    run_id: str
    seq: int
    role: str
    text: str
    created_at: str


@dataclass(frozen=True)
class SearchMessagePage:
    items: tuple[SearchMessage, ...] = ()
    before_seq: int | None = None


class SearchCorpus(Protocol):
    """Host-scoped visible conversation reader; IDs never grant access."""

    user_id: str

    async def threads(self) -> tuple[SearchThread, ...]: ...

    async def revision(self, thread: SearchThread) -> str | None: ...

    async def messages(self, thread: SearchThread, *, before_seq: int | None) -> SearchMessagePage: ...


@dataclass(frozen=True)
class SearchPage:
    items: tuple[SearchMessage, ...] = ()
    cursor: str | None = None
    indexing: bool = False


class WorkspaceSearchProvider(Protocol):
    """Return literal, case-insensitive matches. Host rechecks each candidate.

    Cursor is provider-owned, opaque and scoped to the query. Services own index
    resources and stop background work before host storage closes.
    """

    async def search(self, corpus: SearchCorpus, *, query: str, threads: tuple[SearchThread, ...], limit: int, cursor: str | None = None) -> SearchPage: ...
