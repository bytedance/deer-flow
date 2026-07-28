from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    ENABLED = "enabled"
    PAUSED = "paused"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContextMode(StrEnum):
    FRESH_THREAD_PER_RUN = "fresh_thread_per_run"
    REUSE_THREAD = "reuse_thread"


class ScheduleType(StrEnum):
    ONCE = "once"
    CRON = "cron"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    SKIPPED = "skipped"


class TriggerKind(StrEnum):
    """What caused a dispatch.

    The two kinds diverge in almost every decision the domain makes — how an
    overlap is handled, what status survives a failed launch, whether a paused
    task stays paused — so this is a first-class concept rather than the raw
    string the old service compared in four places.
    """

    SCHEDULED = "scheduled"
    MANUAL = "manual"
