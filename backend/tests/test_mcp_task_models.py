import pytest

from deerflow.mcp.tasks import McpTaskDriverRegistry, TaskSnapshot, TaskStatus, TaskSubmission, TaskSubmitRequest


def test_task_snapshot_normalizes_string_statuses():
    snapshot = TaskSnapshot(status="working")  # type: ignore[arg-type]
    assert snapshot.status is TaskStatus.WORKING
    assert snapshot.is_pollable is True


def test_input_required_snapshot_requires_payload():
    with pytest.raises(ValueError, match="requires an input_required payload"):
        TaskSnapshot(status=TaskStatus.INPUT_REQUIRED)


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


def test_task_snapshot_rejects_non_finite_poll_interval():
    with pytest.raises(ValueError, match="finite positive"):
        TaskSnapshot(status=TaskStatus.WORKING, poll_after_seconds=float("inf"))


def test_driver_registry_rejects_duplicate_names():
    registry = McpTaskDriverRegistry()
    driver = object()
    registry.register("ordinary", driver)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already registered"):
        registry.register("ordinary", driver)  # type: ignore[arg-type]
