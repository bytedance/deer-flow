from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.mcp_tasks import McpTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.mcp.tasks import (
    ORDINARY_MCP_TASK_DRIVER,
    McpTaskDriverRegistry,
    OrdinaryMcpTaskDriver,
    TaskSubmitRequest,
)
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.mcp_tasks import McpTaskRepository


@pytest_asyncio.fixture(autouse=True)
async def _close_persistence_engine():
    yield
    await close_engine()


class FakeMcpServer:
    def __init__(self):
        self.status_results = []

    async def call_tool(self, *, tool_name, arguments, **_scope):
        if tool_name == "submit_report":
            return SimpleNamespace(
                structuredContent={"task_id": arguments["remote_id"], "status": "running"},
                content=[],
                isError=False,
            )
        if tool_name == "status_report":
            return SimpleNamespace(
                structuredContent=self.status_results.pop(0),
                content=[],
                isError=False,
            )
        if tool_name == "cancel_report":
            return SimpleNamespace(
                structuredContent={"task_id": arguments["task_id"], "status": "cancelled"},
                content=[],
                isError=False,
            )
        raise AssertionError(tool_name)


def _service(repo, fake_server) -> McpTaskService:
    registry = McpTaskDriverRegistry()
    registry.register(ORDINARY_MCP_TASK_DRIVER, OrdinaryMcpTaskDriver(fake_server))
    return McpTaskService(
        repository=repo,
        drivers=registry,
        poll_interval_seconds=1,
        lease_seconds=120,
        max_concurrent_polls=8,
    )


def _request(remote_id: str) -> TaskSubmitRequest:
    return TaskSubmitRequest(
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        task_name="report-generation",
        arguments={"remote_id": remote_id},
        driver_data={
            "submit_tool": "submit_report",
            "status_tool": "status_report",
            "cancel_tool": "cancel_report",
        },
    )


@pytest.mark.asyncio
async def test_submit_poll_restart_recovery_complete_and_fail(tmp_path) -> None:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    repo = McpTaskRepository(session_factory)
    fake_server = FakeMcpServer()
    submitted_at = datetime.now(UTC)
    fake_server.status_results.extend(
        [
            {
                "task_id": "remote-complete",
                "status": "running",
                "poll_after_seconds": 1,
            },
            {
                "task_id": "remote-complete",
                "status": "completed",
                "result": {"report": "ready"},
            },
        ]
    )

    first_process = _service(repo, fake_server)
    created = await first_process.submit(
        driver_name=ORDINARY_MCP_TASK_DRIVER,
        request=_request("remote-complete"),
        now=submitted_at,
    )
    await first_process.run_once(now=submitted_at + timedelta(seconds=2))

    # Recreate the service/registry to model a Gateway restart. The only handle
    # available to the new process is the row persisted before submit returned.
    restarted_process = _service(repo, fake_server)
    await restarted_process.run_once(now=datetime.now(UTC) + timedelta(seconds=2))

    completed = await repo.get(created["id"], user_id="user-1")
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["result"] == {"report": "ready"}

    fake_server.status_results.append(
        {
            "task_id": "remote-fail",
            "status": "failed",
            "error": "report generation failed",
        }
    )
    failed_created = await restarted_process.submit(
        driver_name=ORDINARY_MCP_TASK_DRIVER,
        request=_request("remote-fail"),
        now=datetime.now(UTC) - timedelta(seconds=2),
    )
    await restarted_process.run_once(now=datetime.now(UTC))

    failed = await repo.get(failed_created["id"], user_id="user-1")
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error"] == "report generation failed"
