"""Tests for the run-completion driving adapter.

Every run in the process reaches the run runtime's completion callback, so
this adapter's first job is deciding which of them the schedule context has
any business with -- the filtering the legacy hook did inline, with four guard
clauses and an `if/elif` chain over runtime strings. A run that is not a
scheduled execution produces no call at all, which is why the service carries
no guard clauses of its own and never imports the run runtime.

Driven through `__call__` rather than a conversion function: "was the use case
invoked, and with what" is the behaviour, and the previous split -- a pure
converter here plus the invoking closure in the composition root -- left that
second half untested, since the composition root is not where behaviour is
asserted.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.schedule.run_completion import ScheduleRunCompletionListener
from deerflow.domain.schedule.model import RunStatus
from deerflow.domain.schedule.ports import RunOutcome
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode
from deerflow.runtime.runs.schemas import RunStatus as RuntimeRunStatus

pytestmark = pytest.mark.asyncio

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


class _RecordingService:
    """Stands in for `ScheduleService`, capturing what the use case received."""

    def __init__(self) -> None:
        self.calls: list[tuple[RunOutcome, datetime]] = []

    async def handle_run_completion(self, outcome: RunOutcome, *, now: datetime) -> None:
        self.calls.append((outcome, now))


async def _delivered(record) -> RunOutcome | None:
    """The outcome the service was called with, or None when it was not."""
    service = _RecordingService()
    await ScheduleRunCompletionListener(service)(record)
    return service.calls[0][0] if service.calls else None


class TestTerminalStatusMapping:
    async def test_success(self):
        assert await _delivered(_record(status=RuntimeRunStatus.success)) == RunOutcome(
            task_id="task-1",
            record_id="rec-1",
            run_id="run-1",
            user_id="user-1",
            status=RunStatus.SUCCESS,
            error=None,
        )

    async def test_a_successful_run_carries_no_error_even_if_the_record_has_one(self):
        """A stale `error` on a successful record must not be written back as
        the task's `last_error`; success is success."""
        outcome = await _delivered(_record(status=RuntimeRunStatus.success, error="stale"))
        assert outcome is not None and outcome.error is None

    @pytest.mark.parametrize("status", [RuntimeRunStatus.error, RuntimeRunStatus.timeout])
    async def test_error_and_timeout_both_become_failed(self, status):
        outcome = await _delivered(_record(status=status, error="boom"))
        assert outcome is not None
        assert outcome.status is RunStatus.FAILED
        assert outcome.error == "boom"

    async def test_interrupted_is_distinct_from_failed(self):
        """Red line: a cancel or same-thread takeover is not an execution
        failure -- the task must end CANCELLED, and only INTERRUPTED gets it
        there."""
        outcome = await _delivered(_record(status=RuntimeRunStatus.interrupted))
        assert outcome is not None and outcome.status is RunStatus.INTERRUPTED

    async def test_an_interrupt_without_an_error_gets_an_explanatory_one(self):
        outcome = await _delivered(_record(status=RuntimeRunStatus.interrupted, error=None))
        assert outcome is not None and outcome.error == "run was interrupted before completion"

    async def test_an_interrupts_own_error_is_preserved(self):
        outcome = await _delivered(_record(status=RuntimeRunStatus.interrupted, error="cancelled by user"))
        assert outcome is not None and outcome.error == "cancelled by user"


class TestFilteredOut:
    """None of these reach the service at all -- not as an error, not as a
    no-op call it has to recognise."""

    @pytest.mark.parametrize("status", [RuntimeRunStatus.pending, RuntimeRunStatus.running])
    async def test_a_non_terminal_run_is_ignored(self, status):
        assert await _delivered(_record(status=status)) is None

    async def test_an_ordinary_chat_run_is_ignored(self):
        """Every run in the process reaches this callback; only scheduled
        executions carry the metadata that makes one ours."""
        assert await _delivered(_record(status=RuntimeRunStatus.success, metadata={})) is None

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
    async def test_half_or_mistyped_metadata_is_ignored(self, metadata):
        """Both ids are required and both must be strings -- `metadata` is a
        free-form dict a client can influence, so its shape is not assumed."""
        assert await _delivered(_record(status=RuntimeRunStatus.success, metadata=metadata)) is None

    @pytest.mark.parametrize("user_id", [None, ""])
    async def test_a_run_without_an_owner_is_ignored(self, user_id):
        """Every task read is scoped by user_id; without one there is no
        authorized way to look the task up."""
        assert await _delivered(_record(status=RuntimeRunStatus.success, user_id=user_id)) is None

    async def test_none_metadata_is_ignored(self):
        """`metadata` is typed as a dict but the legacy hook defended against
        `None`; keep that defence rather than rediscovering it in production."""
        assert await _delivered(_record(status=RuntimeRunStatus.success, metadata=None)) is None

    async def test_the_service_is_left_entirely_alone(self):
        """Explicitly: not called, rather than called with something falsy.

        This half had no coverage while the invoking closure lived in the
        composition root.
        """
        service = _RecordingService()
        await ScheduleRunCompletionListener(service)(_record(status=RuntimeRunStatus.running))
        assert service.calls == []


class TestUseCaseInvocation:
    async def test_the_completion_is_stamped_with_the_current_instant(self):
        service = _RecordingService()
        before = datetime.now(UTC)
        await ScheduleRunCompletionListener(service)(_record(status=RuntimeRunStatus.success))
        after = datetime.now(UTC)

        assert len(service.calls) == 1
        _, now = service.calls[0]
        assert now.tzinfo is not None, "the domain is tz-aware throughout"
        assert before <= now <= after

    async def test_one_finished_run_produces_exactly_one_call(self):
        service = _RecordingService()
        await ScheduleRunCompletionListener(service)(_record(status=RuntimeRunStatus.success))
        assert len(service.calls) == 1
