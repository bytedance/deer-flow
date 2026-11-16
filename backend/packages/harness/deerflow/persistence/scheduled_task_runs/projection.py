"""Parent projection and launch accounting under the scheduled-task row lock."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.orm.attributes import flag_modified

from deerflow.scheduler.schedules import pauses_unschedulable

if TYPE_CHECKING:
    from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

logger = logging.getLogger(__name__)


def can_project(task: ScheduledTaskRow, occurrence: ScheduledTaskRunRow) -> bool:
    """Keep unsequenced history best-effort until a sequenced run is admitted."""
    if occurrence.occurrence_seq is None:
        return task.last_occurrence_seq == 0
    return occurrence.occurrence_seq == task.last_occurrence_seq


def once_run_still_scheduled(task: ScheduledTaskRow, occurrence: ScheduledTaskRunRow) -> bool:
    """Whether a ``once`` task's own run is still ahead of this trial.

    A manual trigger is a trial ("Run once now"): launched before the run
    time it must not consume that run, so the parent keeps its status rather
    than taking the once outcome. ``next_run_at`` holds the run time only
    while it was still ahead at the trial's launch; the launch write (or the
    projection repairing it) clears it otherwise. Always False for a recurring
    task, whose ``next_run_at`` is set between runs. The launch path, which
    has no occurrence row yet, encodes the same rule in
    ``ScheduledTaskService._task_status_for_launch``.
    """
    return task.schedule_type == "once" and occurrence.trigger == "manual" and task.next_run_at is not None


def account_launch(task: ScheduledTaskRow, occurrence: ScheduledTaskRunRow, run_id: str) -> bool:
    """Count a proven launch once, in the same transaction as its marker.

    Migrated NULL markers retain the old last_run_id inference for their first
    repair; historical accounting cannot be reconstructed from occurrence times.
    """
    if occurrence.launch_accounted is True:
        return False
    legacy = occurrence.launch_accounted is None
    occurrence.launch_accounted = True
    if legacy and task.last_run_id == run_id:
        return False
    task.run_count += 1
    # A stale occurrence may change the count, but not the current projection's
    # timestamp. Callers that also project a result explicitly set updated_at.
    flag_modified(task, "updated_at")
    return True


def pause_unschedulable(task: ScheduledTaskRow, schedule_error: str | None) -> None:
    """Pause a recurring task whose stored schedule no longer computes.

    Its cursor is already cleared, so nothing would claim it again; the pause
    and ``last_error`` say why. See ``stored_next_run_at``.
    """
    if not pauses_unschedulable(task.schedule_type, task.status, schedule_error):
        return
    logger.warning("Paused scheduled task %s: %s", task.id, schedule_error)
    task.status = "paused"
    task.last_error = schedule_error
