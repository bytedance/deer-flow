from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class InvalidMetadataFilterError(ValueError):
    """Raised when all client-supplied metadata filters are rejected."""


class ThreadMetaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    assistant_id: str | None = None
    user_id: str | None = None
    display_name: str | None = None
    status: str = "idle"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    assistant_id: str | None
    user_id: str | None
    display_name: str | None
    status: str
    metadata: dict[str, Any]
    created_time: datetime
    updated_time: datetime | None


class ThreadMetaRepositoryProtocol(Protocol):
    async def create_thread_meta(self, data: ThreadMetaCreate) -> ThreadMeta:
        pass

    async def get_thread_meta(self, thread_id: str) -> ThreadMeta | None:
        pass

    async def update_thread_meta(
        self,
        thread_id: str,
        *,
        display_name: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        pass

    async def delete_thread(self, thread_id: str) -> None:
        pass

    async def search_threads(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        user_id: str | None = None,
        assistant_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ThreadMeta]:
        pass
