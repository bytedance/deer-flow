"""Application query DTOs for run use cases."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import RunId, ThreadId, UserId


@dataclass(frozen=True)
class GetRunQuery:
    run_id: RunId
    thread_id: ThreadId | None = None
    user_id: UserId | None = None


@dataclass(frozen=True)
class ListRunsQuery:
    thread_id: ThreadId
    user_id: UserId | None = None
    limit: int = 100


@dataclass(frozen=True)
class ListRunMessagesQuery:
    thread_id: ThreadId
    run_id: RunId
    limit: int = 50
    before_seq: int | None = None
    after_seq: int | None = None


__all__ = [
    "GetRunQuery",
    "ListRunMessagesQuery",
    "ListRunsQuery",
]
