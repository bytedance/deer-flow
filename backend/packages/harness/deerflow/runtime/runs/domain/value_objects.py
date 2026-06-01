"""Domain value objects for run lifecycle semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RunStatus(StrEnum):
    """Lifecycle status of a single run."""

    pending = "pending"
    running = "running"
    success = "success"
    error = "error"
    timeout = "timeout"
    interrupted = "interrupted"


class DisconnectMode(StrEnum):
    """Behaviour when the SSE consumer disconnects."""

    cancel = "cancel"
    continue_ = "continue"


class RunScope(StrEnum):
    """Conversation scope for a run."""

    stateful = "stateful"
    stateless = "stateless"
    temporary_thread = "temporary_thread"


class MultitaskStrategy(StrEnum):
    """Concurrency strategy for a new run on a thread."""

    reject = "reject"
    interrupt = "interrupt"
    rollback = "rollback"
    enqueue = "enqueue"


class CancelAction(StrEnum):
    """Cancellation action requested by an API or supervisor."""

    interrupt = "interrupt"
    rollback = "rollback"


TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.success,
        RunStatus.error,
        RunStatus.timeout,
        RunStatus.interrupted,
    }
)


def is_terminal_status(status: RunStatus) -> bool:
    return status in TERMINAL_RUN_STATUSES


@dataclass(frozen=True, order=True)
class EventSeq:
    """Thread-local event sequence number."""

    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("EventSeq must be non-negative")

    def next(self) -> EventSeq:
        return EventSeq(self.value + 1)


__all__ = [
    "CancelAction",
    "DisconnectMode",
    "EventSeq",
    "MultitaskStrategy",
    "RunScope",
    "RunStatus",
    "TERMINAL_RUN_STATUSES",
    "is_terminal_status",
]
