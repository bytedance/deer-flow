"""Boundary tests for the RunRecord -> RunOutcome conversion.

This converter is where the completion hook's inline filtering moved to. The
old `handle_run_completion` opened with four guard clauses and a status
`if/elif` chain over runtime strings; the service now receives a `RunOutcome`
or is never called at all, so all of that lives here and the domain never
imports the run runtime.

`None` therefore has one meaning: *this run is none of the schedule context's
business*. It is not an error and must never reach the service.
"""

from __future__ import annotations

import pytest

from app.adapters.schedule.run_outcome_mapping import run_outcome_from_record
from deerflow.domain.schedule.model import RunStatus
from deerflow.domain.schedule.ports import RunOutcome
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode
from deerflow.runtime.runs.schemas import RunStatus as RuntimeRunStatus

TASK_METADATA = {
    "scheduled_task_id": "task-1",
    "scheduled_task_run_id": "rec-1",
    "scheduled_trigger": "scheduled",
}


_DEFAULT = object()


def _record(*, status, metadata=_DEFAULT, user_id="user-1", error=None, run_id="run-1"):
    return RunRecord(
        run_id=run_id,
        thread_id="thread-1",
        assistant_id=None,
        status=status,
        on_disconnect=DisconnectMode.continue_,
        metadata=TASK_METADATA if metadata is _DEFAULT else metadata,
        user_id=user_id,
        error=error,
    )


class TestTerminalStatusMapping:
    def test_success(self):
        outcome = run_outcome_from_record(_record(status=RuntimeRunStatus.success))
        assert outcome == RunOutcome(
            task_id="task-1",
            record_id="rec-1",
            run_id="run-1",
            user_id="user-1",
            status=RunStatus.SUCCESS,
            error=None,
        )

    def test_a_successful_run_carries_no_error_even_if_the_record_has_one(self):
        """A stale `error` on a successful record must not be written back as
        the task's `last_error`; success is success."""
        outcome = run_outcome_from_record(_record(status=RuntimeRunStatus.success, error="stale"))
        assert outcome is not None and outcome.error is None

    @pytest.mark.parametrize("status", [RuntimeRunStatus.error, RuntimeRunStatus.timeout])
    def test_error_and_timeout_both_become_failed(self, status):
        outcome = run_outcome_from_record(_record(status=status, error="boom"))
        assert outcome is not None
        assert outcome.status is RunStatus.FAILED
        assert outcome.error == "boom"

    def test_interrupted_is_distinct_from_failed(self):
        """Red line: a cancel or same-thread takeover is not an execution
        failure -- the task must end CANCELLED, and only INTERRUPTED gets it
        there."""
        outcome = run_outcome_from_record(_record(status=RuntimeRunStatus.interrupted))
        assert outcome is not None and outcome.status is RunStatus.INTERRUPTED

    def test_an_interrupt_without_an_error_gets_an_explanatory_one(self):
        outcome = run_outcome_from_record(_record(status=RuntimeRunStatus.interrupted, error=None))
        assert outcome is not None and outcome.error == "run was interrupted before completion"

    def test_an_interrupts_own_error_is_preserved(self):
        outcome = run_outcome_from_record(_record(status=RuntimeRunStatus.interrupted, error="cancelled by user"))
        assert outcome is not None and outcome.error == "cancelled by user"


class TestFilteredOut:
    @pytest.mark.parametrize("status", [RuntimeRunStatus.pending, RuntimeRunStatus.running])
    def test_a_non_terminal_run_produces_nothing(self, status):
        assert run_outcome_from_record(_record(status=status)) is None

    def test_a_run_with_no_metadata_produces_nothing(self):
        """An ordinary chat run reaches the same completion hook; it is not a
        scheduled execution and must not be written back as one."""
        assert run_outcome_from_record(_record(status=RuntimeRunStatus.success, metadata={})) is None

    @pytest.mark.parametrize(
        "metadata",
        [
            {"scheduled_task_run_id": "rec-1"},
            {"scheduled_task_id": "task-1"},
            {"scheduled_task_id": "task-1", "scheduled_task_run_id": None},
            {"scheduled_task_id": 7, "scheduled_task_run_id": "rec-1"},
            {"scheduled_task_id": "task-1", "scheduled_task_run_id": 7},
        ],
    )
    def test_half_or_mistyped_metadata_produces_nothing(self, metadata):
        """Both ids are required and both must be strings -- `metadata` is a
        free-form dict a client can influence, so its shape is not assumed."""
        assert run_outcome_from_record(_record(status=RuntimeRunStatus.success, metadata=metadata)) is None

    @pytest.mark.parametrize("user_id", [None, ""])
    def test_a_run_without_an_owner_produces_nothing(self, user_id):
        """Every task read is scoped by user_id; without one there is no
        authorized way to look the task up."""
        assert run_outcome_from_record(_record(status=RuntimeRunStatus.success, user_id=user_id)) is None

    def test_a_none_metadata_produces_nothing(self):
        """`metadata` is typed as a dict but the legacy hook defended against
        `None`; keep that defence rather than rediscovering it in production."""
        assert run_outcome_from_record(_record(status=RuntimeRunStatus.success, metadata=None)) is None
