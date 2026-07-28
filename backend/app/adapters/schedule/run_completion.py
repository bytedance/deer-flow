"""Primary adapter (inbound) -- the run runtime's completion callback.

The one file in this package that drives the domain rather than serving it.
Its siblings are secondary adapters the service calls out to; this one is
called *by* the run runtime, the same way the router is called by HTTP and the
poller by its clock. Kept here rather than beside those two so the context
stays in one place, with the direction stated by the name and by this line.

Its job is the filtering the legacy completion hook did inline. Every run in
the process reaches that callback, so most of them are none of this context's
business, and producing no call at all says exactly that -- not an error, just
nothing to write back. That is why `ScheduleService.handle_run_completion`
carries no guard clauses and never imports ``RunRecord``.

TODO(hexagonal): this depends on ``RunRecord``, a run-runtime type, rather
than on a contract published by the run context -- that context has not been
through a hexagonal slice yet. When it publishes one (a DTO, not its aggregate
and not its repository), replace ``_to_outcome``. Nothing else moves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from deerflow.domain.schedule.model import RunStatus
from deerflow.domain.schedule.ports import RunOutcome

if TYPE_CHECKING:
    from deerflow.domain.schedule.service import ScheduleService
    from deerflow.runtime import RunRecord

# The runtime reports four terminal states; the domain has three, because
# `timeout` and `error` are the same fact to a scheduled task while
# `interrupted` is deliberately not -- a cancel or same-thread takeover ends
# the task CANCELLED, not FAILED.
_TERMINAL_STATUSES = {
    "success": RunStatus.SUCCESS,
    "error": RunStatus.FAILED,
    "timeout": RunStatus.FAILED,
    "interrupted": RunStatus.INTERRUPTED,
}

_INTERRUPTED_WITHOUT_ERROR = "run was interrupted before completion"


class ScheduleRunCompletionListener:
    """Turns a finished run into the write-back use case, or into nothing.

    Deciding whether a run is ours and invoking the use case are one
    responsibility, not two: "ignore this run" is only meaningful as "do not
    call the service", so splitting them left the second half living in the
    composition root, where behaviour is not asserted.
    """

    def __init__(self, service: ScheduleService) -> None:
        self._service = service

    async def __call__(self, record: RunRecord) -> None:
        outcome = self._to_outcome(record)
        if outcome is None:
            return
        await self._service.handle_run_completion(outcome, now=datetime.now(UTC))

    @staticmethod
    def _to_outcome(record: RunRecord) -> RunOutcome | None:
        """Translate into domain vocabulary, or `None` to ignore the run.

        `None` when the run is not a scheduled execution (no usable task
        metadata, no owner) or has not reached a terminal state yet.
        """
        metadata = record.metadata or {}
        task_id = metadata.get("scheduled_task_id")
        record_id = metadata.get("scheduled_task_run_id")
        user_id = record.user_id
        # `metadata` is a free-form dict a caller can influence, so the ids are
        # type-checked rather than assumed; `user_id` is required because every
        # task read is scoped by it.
        if not isinstance(task_id, str) or not isinstance(record_id, str) or not user_id:
            return None

        status = _TERMINAL_STATUSES.get(str(record.status.value))
        if status is None:
            return None

        if status is RunStatus.SUCCESS:
            # A stale error left on a successful record must not be written back
            # as the task's last_error.
            error = None
        elif status is RunStatus.INTERRUPTED:
            error = record.error or _INTERRUPTED_WITHOUT_ERROR
        else:
            error = record.error

        return RunOutcome(
            task_id=task_id,
            record_id=record_id,
            run_id=record.run_id,
            user_id=user_id,
            status=status,
            error=error,
        )
