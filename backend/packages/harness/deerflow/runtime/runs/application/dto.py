"""Application output DTOs for run use cases."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ..domain import AssistantId, EventSeq, Run, RunId, RunStatus, ThreadId


@dataclass(frozen=True)
class RunSnapshot:
    run_id: RunId
    thread_id: ThreadId
    assistant_id: AssistantId | None = None
    status: RunStatus = RunStatus.pending
    metadata: dict[str, Any] = field(default_factory=dict)
    kwargs: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    error: str | None = None
    model_name: str | None = None

    @classmethod
    def from_run(cls, run: Run) -> RunSnapshot:
        return cls(
            run_id=run.run_id,
            thread_id=run.thread_id,
            assistant_id=run.assistant_id,
            status=run.status,
            metadata=dict(run.metadata),
            kwargs=dict(run.kwargs),
            created_at=run.created_at,
            updated_at=run.updated_at,
            error=run.error,
            model_name=run.model_name,
        )


@dataclass(frozen=True)
class RunMessageView:
    thread_id: ThreadId
    run_id: RunId
    seq: EventSeq
    event_type: str
    content: str | dict[str, Any] = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True)
class StoredRunEvent:
    thread_id: ThreadId
    run_id: RunId
    seq: EventSeq
    event_type: str
    category: str
    content: str | dict[str, Any] = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True)
class RunStreamHandle:
    run_id: RunId
    thread_id: ThreadId
    events: AsyncIterator[Any]


__all__ = [
    "RunMessageView",
    "RunSnapshot",
    "RunStreamHandle",
    "StoredRunEvent",
]
