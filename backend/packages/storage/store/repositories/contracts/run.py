from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    thread_id: str
    assistant_id: str | None = None
    user_id: str | None = None
    status: str = "pending"
    model_name: str | None = None
    multitask_strategy: str = "reject"
    error: str | None = None
    follow_up_to_run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    created_time: datetime | None = None


class Run(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    thread_id: str
    assistant_id: str | None
    user_id: str | None
    status: str
    model_name: str | None
    multitask_strategy: str
    error: str | None
    follow_up_to_run_id: str | None
    metadata: dict[str, Any]
    kwargs: dict[str, Any]
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    llm_call_count: int
    lead_agent_tokens: int
    subagent_tokens: int
    middleware_tokens: int
    message_count: int
    first_human_message: str | None
    last_ai_message: str | None
    created_time: datetime
    updated_time: datetime | None


class RunRepositoryProtocol(Protocol):
    async def create_run(self, data: RunCreate) -> Run:
        pass

    async def get_run(self, run_id: str) -> Run | None:
        pass

    async def list_runs_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Run]:
        pass

    async def update_run_status(self, run_id: str, status: str, *, error: str | None = None) -> None:
        pass

    async def delete_run(self, run_id: str) -> None:
        pass

    async def list_pending(self, *, before: datetime | str | None = None) -> list[Run]:
        pass

    async def update_run_completion(
        self,
        run_id: str,
        *,
        status: str,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        total_tokens: int = 0,
        llm_call_count: int = 0,
        lead_agent_tokens: int = 0,
        subagent_tokens: int = 0,
        middleware_tokens: int = 0,
        message_count: int = 0,
        first_human_message: str | None = None,
        last_ai_message: str | None = None,
        error: str | None = None,
    ) -> None:
        pass

    async def aggregate_tokens_by_thread(self, thread_id: str) -> dict[str, Any]:
        pass
