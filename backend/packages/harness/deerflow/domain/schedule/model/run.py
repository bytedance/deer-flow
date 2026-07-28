from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from deerflow.domain.schedule.model.enums import RunStatus

ACTIVE_RUN_STATUSES: tuple[RunStatus, ...] = (RunStatus.QUEUED, RunStatus.RUNNING)
"""The statuses that occupy a task's single active-run slot.

Must stay in lockstep with the predicate of the partial unique index
``uq_scheduled_task_run_active`` (``status IN ('queued','running')``, declared
in ``persistence/scheduled_task_runs/model.py``). Drift here silently
decouples the overlap fast path from its atomic arbiter — the consistency
assertion lives in a separate test module rather than the domain tests, which
stay dependency-free.
"""

TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.SUCCESS,
        RunStatus.FAILED,
        RunStatus.SKIPPED,
        RunStatus.INTERRUPTED,
    }
)
"""Statuses a run row can no longer leave.

Used by the repository's ``protect_terminal`` compare-and-set: a fast-failing
run can reach the completion hook before the launch path's own write lands.
"""


@dataclass(frozen=True)
class ScheduledRun:
    """One execution record of a scheduled task — the history row.

    A separate aggregate from ``ScheduledTask``: the two are written in
    independent transactions and reference each other only by ``task_id``.
    """

    record_id: str
    task_id: str
    thread_id: str
    scheduled_for: datetime
    trigger: str
    status: RunStatus
    run_id: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def queued(cls, *, task_id: str, thread_id: str, scheduled_for: datetime, trigger: str) -> ScheduledRun:
        """The active row of a normal dispatch.

        Inserting this is what the unique index arbitrates: the loser of a
        concurrent insert surfaces as ``ActiveRunConflictError``.

        The ``task-run-{hex}`` id shape is depended on by existing rows and by
        the run metadata that links a Gateway run back to this record — do not
        change it.
        """
        return cls(
            record_id=f"task-run-{uuid.uuid4().hex}",
            task_id=task_id,
            thread_id=thread_id,
            scheduled_for=scheduled_for,
            trigger=trigger,
            status=RunStatus.QUEUED,
        )

    @classmethod
    def skipped_tombstone(cls, *, task_id: str, thread_id: str, scheduled_for: datetime, trigger: str) -> ScheduledRun:
        """A dropped occurrence, created directly as terminal ``SKIPPED``.

        Deliberately a second factory rather than ``queued()`` followed by a
        status change: ``QUEUED`` falls inside ``uq_scheduled_task_run_active``'s
        predicate and would collide with the pre-existing run that still holds
        the task's single active slot. ``SKIPPED`` is outside the predicate and
        can never conflict (service.py:249-256).
        """
        return cls(
            record_id=f"task-run-{uuid.uuid4().hex}",
            task_id=task_id,
            thread_id=thread_id,
            scheduled_for=scheduled_for,
            trigger=trigger,
            status=RunStatus.SKIPPED,
        )

    @property
    def is_active(self) -> bool:
        """Whether this row occupies the task's single active-run slot."""
        return self.status in ACTIVE_RUN_STATUSES
