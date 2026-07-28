"""Boundary mapping (not a port implementation) -- RunRecord -> RunOutcome.

Unlike its siblings in this package, this module implements no port: it is the
inbound translation the composition root installs on the run runtime's
completion hook, so the domain never imports ``RunRecord``.

It also owns the filtering the legacy completion hook did inline. Every run in
the process reaches that hook, so most of them are none of this context's
business, and returning ``None`` says exactly that -- not an error, just
nothing to write back. The service is then never called at all, which is why it
has no guard clauses of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deerflow.domain.schedule.model import RunStatus
from deerflow.domain.schedule.ports import RunOutcome

if TYPE_CHECKING:
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


def run_outcome_from_record(record: RunRecord) -> RunOutcome | None:
    """Translate a finished run into domain vocabulary, or `None` to ignore it.

    `None` is returned when the run is not a scheduled execution (no usable
    task metadata, no owner) or has not reached a terminal state yet.
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
        # A stale error left on a successful record must not be written back as
        # the task's last_error.
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
