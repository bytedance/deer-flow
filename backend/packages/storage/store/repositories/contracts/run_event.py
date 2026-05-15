from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class RunEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    run_id: str
    user_id: str | None = None
    event_type: str
    category: str
    content: Any = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class RunEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    run_id: str
    user_id: str | None
    event_type: str
    category: str
    content: Any
    metadata: dict[str, Any]
    seq: int
    created_at: datetime


class RunEventRepositoryProtocol(Protocol):
    # Sequence values are time-ordered integer cursors. The application layer
    # owns the single-writer invariant for a thread while a run is active.
    async def append_batch(self, events: list[RunEventCreate]) -> list[RunEvent]:
        pass

    async def list_messages(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
        user_id: str | None = None,
    ) -> list[RunEvent]:
        pass

    async def list_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 500,
        user_id: str | None = None,
    ) -> list[RunEvent]:
        pass

    async def list_messages_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
        user_id: str | None = None,
    ) -> list[RunEvent]:
        pass

    async def count_messages(self, thread_id: str, *, user_id: str | None = None) -> int:
        pass

    async def delete_by_thread(self, thread_id: str, *, user_id: str | None = None) -> int:
        pass

    async def delete_by_run(self, thread_id: str, run_id: str, *, user_id: str | None = None) -> int:
        pass
