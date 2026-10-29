from datetime import timedelta

import pytest

from deerflow.mcp.tasks import (
    McpTaskDriverRegistry,
    TaskReference,
    TaskSnapshot,
    TaskStatus,
    TaskSubmission,
    TaskSubmitRequest,
)


def test_task_snapshot_normalizes_string_statuses():
    snapshot = TaskSnapshot(status="working")  # type: ignore[arg-type]
    assert snapshot.status is TaskStatus.WORKING
    assert snapshot.is_pollable is True


def test_input_required_snapshot_requires_payload():
    with pytest.raises(ValueError, match="requires an input_required payload"):
        TaskSnapshot(status=TaskStatus.INPUT_REQUIRED)


@pytest.mark.parametrize("interval", [float("nan"), float("inf")])
def test_snapshot_rejects_non_finite_poll_interval(interval):
    with pytest.raises(ValueError, match="poll_after_seconds must be a finite positive number"):
        TaskSnapshot(status=TaskStatus.WORKING, poll_after_seconds=interval)


@pytest.mark.parametrize("interval", [0, -1, float("-inf")])
def test_snapshot_rejects_non_positive_poll_interval(interval):
    with pytest.raises(ValueError, match="poll_after_seconds"):
        TaskSnapshot(status=TaskStatus.WORKING, poll_after_seconds=interval)


def test_snapshot_keeps_valid_poll_interval_schedulable():
    snapshot = TaskSnapshot(status=TaskStatus.WORKING, poll_after_seconds=12.5)
    assert snapshot.poll_after_seconds == 12.5
    assert timedelta(seconds=snapshot.poll_after_seconds) == timedelta(seconds=12.5)


def test_submission_rejects_empty_remote_id():
    with pytest.raises(ValueError, match="remote_task_id must not be empty"):
        TaskSubmission(remote_task_id="  ", snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED))


def test_task_storage_identifiers_reject_values_longer_than_the_database_columns():
    for field_name, request_kwargs in (
        ("server_name", {"server_name": "s" * 129, "task_name": "report"}),
        ("task_name", {"server_name": "reports", "task_name": "t" * 256}),
    ):
        with pytest.raises(ValueError, match=field_name):
            TaskSubmitRequest(
                user_id="user-1",
                thread_id="thread-1",
                run_id=None,
                tool_call_id=None,
                arguments={},
                **request_kwargs,
            )


def test_incarnation_fields_preserve_legacy_positional_construction():
    reference_driver_data = {"status_tool": "status"}
    reference = TaskReference(
        "task-1",
        "user-1",
        "thread-1",
        "reports",
        "remote-1",
        reference_driver_data,
    )
    assert reference.driver_data is reference_driver_data
    assert reference.thread_incarnation is None

    request_driver_data = {"submit_tool": "submit"}
    request = TaskSubmitRequest(
        "user-1",
        "thread-1",
        "run-1",
        "call-1",
        "reports",
        "Generate report",
        {},
        request_driver_data,
        "task-1",
    )
    assert request.driver_data is request_driver_data
    assert request.local_task_id == "task-1"
    assert request.thread_incarnation is None


def test_driver_registry_rejects_duplicate_names():
    registry = McpTaskDriverRegistry()
    driver = object()
    registry.register("ordinary", driver)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already registered"):
        registry.register("ordinary", driver)  # type: ignore[arg-type]
