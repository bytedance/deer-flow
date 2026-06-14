"""Domain events emitted by the run aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deerflow.utils.time import now_iso

from .identifiers import AssistantId, RunId, ThreadId
from .value_objects import CancelAction, RunStatus


@dataclass(frozen=True)
class RunCreated:
    run_id: RunId
    thread_id: ThreadId
    occurred_at: str = field(default_factory=now_iso)
    assistant_id: AssistantId | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunStarted:
    run_id: RunId
    thread_id: ThreadId
    occurred_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class RunCompleted:
    run_id: RunId
    thread_id: ThreadId
    occurred_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class RunFailed:
    run_id: RunId
    thread_id: ThreadId
    status: RunStatus
    occurred_at: str = field(default_factory=now_iso)
    error: str | None = None


@dataclass(frozen=True)
class RunCancelled:
    run_id: RunId
    thread_id: ThreadId
    occurred_at: str = field(default_factory=now_iso)
    action: CancelAction = CancelAction.interrupt


RunEvent = RunCreated | RunStarted | RunCompleted | RunFailed | RunCancelled


__all__ = [
    "RunCancelled",
    "RunCompleted",
    "RunCreated",
    "RunEvent",
    "RunFailed",
    "RunStarted",
]
