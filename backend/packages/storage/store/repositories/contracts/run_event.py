from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class RunEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    run_id: str
    event_type: str
    category: str
    content: str | dict[str, Any] = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class RunEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    run_id: str
    event_type: str
    category: str
    content: str | dict[str, Any]
    metadata: dict[str, Any]
    seq: int
    created_at: datetime


class RunEventRepositoryProtocol(Protocol):
    async def append_batch(self, events: list[RunEventCreate]) -> list[RunEvent]: ...

    async def list_messages(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[RunEvent]: ...

    async def list_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 500,
    ) -> list[RunEvent]: ...

    async def list_messages_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[RunEvent]: ...

    async def count_messages(self, thread_id: str) -> int: ...

    async def delete_by_thread(self, thread_id: str) -> int: ...

    async def delete_by_run(self, thread_id: str, run_id: str) -> int: ...
