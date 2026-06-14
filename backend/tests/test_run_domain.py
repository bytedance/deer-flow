"""Tests for the DDD run domain skeleton."""

import pytest

from deerflow.runtime.runs import DisconnectMode, RunStatus
from deerflow.runtime.runs.domain import (
    AssistantId,
    CancelAction,
    EventSeq,
    InvalidRunTransition,
    MultitaskStrategy,
    Run,
    RunCancelled,
    RunCompleted,
    RunCreated,
    RunFailed,
    RunId,
    RunScope,
    RunStarted,
    ThreadId,
)
from deerflow.runtime.runs.schemas import DisconnectMode as CompatDisconnectMode
from deerflow.runtime.runs.schemas import RunStatus as CompatRunStatus


def test_compat_schema_exports_use_domain_enums() -> None:
    assert CompatRunStatus is RunStatus
    assert CompatDisconnectMode is DisconnectMode


def test_create_run_records_pending_state_and_created_event() -> None:
    run = Run.create(
        run_id=RunId("run-1"),
        thread_id=ThreadId("thread-1"),
        assistant_id=AssistantId("lead_agent"),
        scope=RunScope.stateful,
        multitask_strategy=MultitaskStrategy.reject,
        metadata={"source": "test"},
        kwargs={"input": {"messages": []}},
        created_at="2026-01-01T00:00:00+00:00",
    )

    assert run.status == RunStatus.pending
    assert run.run_id == "run-1"
    assert run.thread_id == "thread-1"
    assert run.assistant_id == "lead_agent"
    assert run.created_at == "2026-01-01T00:00:00+00:00"
    assert run.updated_at == "2026-01-01T00:00:00+00:00"

    events = run.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], RunCreated)
    assert events[0].metadata == {"source": "test"}
    assert run.pull_events() == ()


def test_run_allows_pending_running_success_transition() -> None:
    run = Run.create(run_id=RunId("run-1"), thread_id=ThreadId("thread-1"))
    run.pull_events()

    run.mark_started(at="2026-01-01T00:00:01+00:00")
    run.mark_completed(at="2026-01-01T00:00:02+00:00")

    assert run.status == RunStatus.success
    assert run.updated_at == "2026-01-01T00:00:02+00:00"
    events = run.pull_events()
    assert [type(event) for event in events] == [RunStarted, RunCompleted]


def test_run_records_failed_and_cancelled_domain_events() -> None:
    failed = Run.create(run_id=RunId("run-failed"), thread_id=ThreadId("thread-1"))
    failed.pull_events()
    failed.mark_started()
    failed.mark_failed("boom", at="2026-01-01T00:00:03+00:00")
    failed_events = failed.pull_events()

    assert failed.status == RunStatus.error
    assert isinstance(failed_events[-1], RunFailed)
    assert failed_events[-1].status == RunStatus.error
    assert failed_events[-1].error == "boom"

    cancelled = Run.create(run_id=RunId("run-cancelled"), thread_id=ThreadId("thread-1"))
    cancelled.pull_events()
    cancelled.mark_cancelled(action=CancelAction.rollback)
    cancelled_events = cancelled.pull_events()

    assert cancelled.status == RunStatus.interrupted
    assert isinstance(cancelled_events[-1], RunCancelled)
    assert cancelled_events[-1].action == CancelAction.rollback


def test_terminal_run_cannot_transition_again() -> None:
    run = Run.create(run_id=RunId("run-1"), thread_id=ThreadId("thread-1"))
    run.mark_started()
    run.mark_completed()

    with pytest.raises(InvalidRunTransition) as exc:
        run.mark_failed("too late")

    assert exc.value.current == RunStatus.success
    assert exc.value.target == RunStatus.error


def test_domain_value_objects_validate_minimal_invariants() -> None:
    assert EventSeq(1).next() == EventSeq(2)
    with pytest.raises(ValueError, match="EventSeq"):
        EventSeq(-1)
    with pytest.raises(ValueError, match="run_id"):
        Run.create(run_id=RunId(" "), thread_id=ThreadId("thread-1"))
