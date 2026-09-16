from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Any

from deerflow.constants import (
    MCP_TASK_NAME_MAX_LENGTH,
    MCP_TASK_SERVER_NAME_MAX_LENGTH,
)


def _validate_storage_text(value: str, *, field_name: str, max_length: int) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > max_length:
        raise ValueError(f"{field_name} must not exceed {max_length} characters")


class TaskStatus(StrEnum):
    """Protocol-neutral lifecycle states for long-running MCP work."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


POLLABLE_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.SUBMITTED,
        TaskStatus.WORKING,
        TaskStatus.INPUT_REQUIRED,
    }
)
TERMINAL_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
)
ATTENTION_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.INPUT_REQUIRED,
        *TERMINAL_TASK_STATUSES,
    }
)


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """One normalized status response returned by a task driver."""

    status: TaskStatus
    result: Any | None = None
    result_preview: str | None = None
    result_truncated: bool = False
    result_artifact: dict[str, str] | None = None
    error: str | None = None
    input_required: dict[str, Any] | None = None
    poll_after_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, TaskStatus):
            object.__setattr__(self, "status", TaskStatus(self.status))
        if self.poll_after_seconds is not None and (not isfinite(self.poll_after_seconds) or self.poll_after_seconds <= 0):
            # NaN and infinity survive a bare `<= 0` check but break the consumer,
            # which turns this interval into a `timedelta` for the next poll.
            raise ValueError("poll_after_seconds must be a finite positive number")
        if self.status == TaskStatus.INPUT_REQUIRED and self.input_required is None:
            raise ValueError("input_required status requires an input_required payload")

    @property
    def is_pollable(self) -> bool:
        return self.status in POLLABLE_TASK_STATUSES

    @property
    def needs_attention(self) -> bool:
        return self.status in ATTENTION_TASK_STATUSES


@dataclass(frozen=True, slots=True)
class TaskReference:
    """Stable data a driver needs after the originating Agent run has ended."""

    local_task_id: str
    user_id: str
    thread_id: str
    server_name: str
    remote_task_id: str
    driver_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> TaskReference:
        return cls(
            local_task_id=record["id"],
            user_id=record["user_id"],
            thread_id=record["thread_id"],
            server_name=record["server_name"],
            remote_task_id=record["remote_task_id"],
            driver_data=dict(record.get("driver_data") or {}),
        )


@dataclass(frozen=True, slots=True)
class TaskSubmitRequest:
    """Protocol-neutral request passed to a driver by an MCP tool wrapper."""

    user_id: str
    thread_id: str
    run_id: str | None
    tool_call_id: str | None
    server_name: str
    task_name: str
    arguments: dict[str, Any]
    driver_data: dict[str, Any] = field(default_factory=dict)
    local_task_id: str | None = None

    def __post_init__(self) -> None:
        _validate_storage_text(
            self.server_name,
            field_name="server_name",
            max_length=MCP_TASK_SERVER_NAME_MAX_LENGTH,
        )
        _validate_storage_text(
            self.task_name,
            field_name="task_name",
            max_length=MCP_TASK_NAME_MAX_LENGTH,
        )


@dataclass(frozen=True, slots=True)
class TaskSubmission:
    """A durable remote handle plus its initial normalized state."""

    remote_task_id: str
    snapshot: TaskSnapshot
    driver_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.remote_task_id.strip():
            raise ValueError("remote_task_id must not be empty")
