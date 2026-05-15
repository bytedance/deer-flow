from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_id: str
    run_id: str
    thread_id: str
    rating: int
    user_id: str | None = None
    message_id: str | None = None
    comment: str | None = None


class Feedback(BaseModel):
    model_config = ConfigDict(frozen=True)

    feedback_id: str
    run_id: str
    thread_id: str
    rating: int
    user_id: str | None
    message_id: str | None
    comment: str | None
    created_time: datetime


class FeedbackAggregate(TypedDict):
    run_id: str
    total: int
    positive: int
    negative: int


class FeedbackRepositoryProtocol(Protocol):
    async def create_feedback(self, data: FeedbackCreate) -> Feedback:
        pass

    async def upsert_feedback(self, data: FeedbackCreate) -> Feedback:
        pass

    async def get_feedback(self, feedback_id: str) -> Feedback | None:
        pass

    async def list_feedback_by_run(
        self,
        run_id: str,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[Feedback]:
        pass

    async def list_feedback_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[Feedback]:
        pass

    async def delete_feedback(self, feedback_id: str) -> bool:
        pass

    async def delete_feedback_by_run(self, thread_id: str, run_id: str, *, user_id: str | None = None) -> bool:
        pass

    async def aggregate_feedback_by_run(self, thread_id: str, run_id: str) -> FeedbackAggregate:
        pass
