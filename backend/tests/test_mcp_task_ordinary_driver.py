from types import SimpleNamespace

import pytest

from deerflow.mcp.tasks import TaskReference, TaskStatus, TaskSubmitRequest
from deerflow.mcp.tasks.ordinary import McpTaskProtocolError, OrdinaryMcpTaskDriver


class FakeCaller:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def call_tool(self, **kwargs):
        self.calls.append(kwargs)
        return self.results.pop(0)


def _result(structured_content, *, text="ignored", is_error=False):
    return SimpleNamespace(
        structuredContent=structured_content,
        content=[SimpleNamespace(text=text)],
        isError=is_error,
    )


def _request() -> TaskSubmitRequest:
    return TaskSubmitRequest(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        task_name="report-generation",
        arguments={"topic": "MCP"},
        driver_data={
            "submit_tool": "submit_report",
            "status_tool": "get_report_status",
            "cancel_tool": "cancel_report",
        },
        local_task_id="local-1",
    )


def _reference() -> TaskReference:
    return TaskReference(
        local_task_id="local-1",
        user_id="user-1",
        thread_id="thread-1",
        server_name="reports",
        remote_task_id="remote-1",
        driver_data={
            "submit_tool": "submit_report",
            "status_tool": "get_report_status",
            "cancel_tool": "cancel_report",
        },
    )


@pytest.mark.asyncio
async def test_submit_uses_structured_content_and_keeps_remote_id_out_of_driver_data() -> None:
    caller = FakeCaller(_result({"task_id": "remote-1", "status": "running"}, text='{"task_id":"wrong"}'))
    driver = OrdinaryMcpTaskDriver(caller)

    submission = await driver.submit(_request())

    assert submission.remote_task_id == "remote-1"
    assert submission.snapshot.status == TaskStatus.SUBMITTED
    assert "remote_task_id" not in submission.driver_data
    assert caller.calls == [
        {
            "server_name": "reports",
            "tool_name": "submit_report",
            "arguments": {"topic": "MCP"},
            "user_id": "user-1",
            "thread_id": "thread-1",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "structured_content,match",
    [
        (None, "structuredContent"),
        ({"status": "running"}, "task_id"),
        ({"task_id": "remote-1", "status": "queued"}, "status"),
    ],
)
async def test_submit_rejects_missing_or_invalid_structured_content(structured_content, match: str) -> None:
    driver = OrdinaryMcpTaskDriver(FakeCaller(_result(structured_content, text='{"task_id":"remote-from-text"}')))

    with pytest.raises(McpTaskProtocolError, match=match):
        await driver.submit(_request())


@pytest.mark.asyncio
async def test_status_maps_all_protocol_states_and_preserves_artifact() -> None:
    caller = FakeCaller(
        _result({"task_id": "remote-1", "status": "running", "poll_after_seconds": 7}),
        _result(
            {
                "task_id": "remote-1",
                "status": "completed",
                "result": {"report": "ready"},
                "result_artifact": {"uri": "s3://reports/1.json", "mime_type": "application/json"},
            }
        ),
    )
    driver = OrdinaryMcpTaskDriver(caller)

    running = await driver.get_status(_reference())
    completed = await driver.get_status(_reference())

    assert running.status == TaskStatus.WORKING
    assert running.poll_after_seconds == 7
    assert completed.status == TaskStatus.COMPLETED
    assert completed.result == {"report": "ready"}
    assert completed.result_artifact == {
        "uri": "s3://reports/1.json",
        "mime_type": "application/json",
    }
    assert caller.calls[0]["arguments"] == {"task_id": "remote-1"}


@pytest.mark.asyncio
async def test_status_keeps_input_required_pollable() -> None:
    driver = OrdinaryMcpTaskDriver(
        FakeCaller(
            _result(
                {
                    "task_id": "remote-1",
                    "status": "input_required",
                    "input_required": {"prompt": "Approve deployment?"},
                }
            )
        )
    )

    snapshot = await driver.get_status(_reference())

    assert snapshot.status == TaskStatus.INPUT_REQUIRED
    assert snapshot.input_required == {"prompt": "Approve deployment?"}
    assert snapshot.is_pollable is True


@pytest.mark.asyncio
async def test_status_turns_task_not_found_into_permanent_failure() -> None:
    driver = OrdinaryMcpTaskDriver(
        FakeCaller(
            _result(
                {
                    "task_id": "remote-1",
                    "status": "running",
                    "error_code": "task_not_found",
                    "error": "expired",
                }
            )
        )
    )

    snapshot = await driver.get_status(_reference())

    assert snapshot.status == TaskStatus.FAILED
    assert snapshot.error == "expired"


@pytest.mark.asyncio
async def test_status_rejects_mismatched_remote_id_and_unknown_status() -> None:
    caller = FakeCaller(
        _result({"task_id": "another-task", "status": "running"}),
        _result({"task_id": "remote-1", "status": "paused"}),
    )
    driver = OrdinaryMcpTaskDriver(caller)

    with pytest.raises(McpTaskProtocolError, match="task_id does not match"):
        await driver.get_status(_reference())
    with pytest.raises(McpTaskProtocolError, match="status"):
        await driver.get_status(_reference())


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["cancelled", "completed", "failed"])
async def test_cancel_is_idempotent_and_preserves_actual_terminal_status(status: str) -> None:
    driver = OrdinaryMcpTaskDriver(FakeCaller(_result({"task_id": "remote-1", "status": status})))

    snapshot = await driver.cancel(_reference())

    assert snapshot.status.value == status
