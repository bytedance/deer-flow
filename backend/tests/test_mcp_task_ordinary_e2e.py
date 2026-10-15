from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.mcp_tasks import McpTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.task_tool_caller import McpTaskToolCaller
from deerflow.mcp.tasks import (
    ORDINARY_MCP_TASK_DRIVER,
    McpTaskDriverRegistry,
    OrdinaryMcpTaskDriver,
    TaskSubmitRequest,
)
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import get_current_user, reset_current_user, set_current_user


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
            status_result = self.status_results.pop(0)
            if not isinstance(status_result, dict):
                return status_result
            return SimpleNamespace(
                structuredContent=status_result,
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
        thread_incarnation="incarnation-1",
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


async def _create_thread(repo: McpTaskRepository) -> None:
    now = datetime.now(UTC)
    async with repo._sf() as session:
        session.add(
            ThreadMetaRow(
                thread_id="thread-1",
                incarnation="incarnation-1",
                user_id="user-1",
                metadata_json={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_submit_poll_restart_recovery_complete_and_fail(tmp_path) -> None:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    repo = McpTaskRepository(session_factory)
    await _create_thread(repo)
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

    completed = await repo.get(created["id"], user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-1")
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

    failed = await repo.get(failed_created["id"], user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-1")
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error"] == "report generation failed"


@pytest.mark.asyncio
async def test_status_tool_error_retries_with_detail_before_structured_failure_terminalizes(tmp_path) -> None:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    repo = McpTaskRepository(session_factory)
    await _create_thread(repo)
    fake_server = FakeMcpServer()
    service = _service(repo, fake_server)
    submitted_at = datetime.now(UTC)
    created = await service.submit(
        driver_name=ORDINARY_MCP_TASK_DRIVER,
        request=_request("remote-fail"),
        now=submitted_at,
    )
    fake_server.status_results.extend(
        [
            SimpleNamespace(
                structuredContent=None,
                content=[SimpleNamespace(type="text", text="upstream temporarily unavailable")],
                isError=True,
            ),
            {
                "task_id": "remote-fail",
                "status": "failed",
                "error": "report generation failed",
            },
        ]
    )

    await service.run_once(now=submitted_at + timedelta(seconds=2))

    retrying = await repo.get(created["id"], user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-1")
    assert retrying is not None
    assert retrying["status"] == "submitted"
    assert retrying["consecutive_poll_error_count"] == 1
    assert retrying["last_poll_error"] == ("MCP task tool 'status_report' returned an error: upstream temporarily unavailable")
    assert retrying["next_poll_at"] is not None

    await service.run_once(now=datetime.now(UTC) + timedelta(seconds=10))

    failed = await repo.get(created["id"], user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-1")
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error"] == "report generation failed"
    assert failed["consecutive_poll_error_count"] == 0
    assert failed["next_poll_at"] is None


@pytest.mark.asyncio
@pytest.mark.no_auto_user
@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize("operation", ["poll", "cancel"])
async def test_recovered_task_authenticates_as_persisted_owner(tmp_path, monkeypatch, transport: str, operation: str) -> None:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    repo = McpTaskRepository(session_factory)
    await _create_thread(repo)
    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": transport,
                    "url": "https://reports.example.com/mcp",
                    "headers": {"Authorization": "Bearer discovery"},
                    "user_auth": {"users": {"user-1": "Bearer task-owner"}},
                    "task_toolsets": [{"name": "reports", "submit_tool": "submit_report", "status_tool": "status_report", "cancel_tool": "cancel_report"}],
                }
            }
        }
    )
    fake_server = FakeMcpServer()
    fake_server.status_results.append({"task_id": "remote-1", "status": "completed", "result": {"report": "ready"}})
    opened_headers = []
    tool_names = []

    async def call_tool(name, arguments):
        tool_names.append(name)
        return await fake_server.call_tool(tool_name=name, arguments=arguments)

    @asynccontextmanager
    async def create_session(connection):
        opened_headers.append(dict(connection["headers"]))
        yield SimpleNamespace(initialize=AsyncMock(), call_tool=call_tool)

    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", create_session)
    first_process = _service(repo, McpTaskToolCaller(config))
    foreground_user = SimpleNamespace(id="user-1")
    user_token = set_current_user(foreground_user)
    try:
        created = await first_process.submit(
            driver_name=ORDINARY_MCP_TASK_DRIVER,
            request=_request("remote-1"),
            now=datetime.now(UTC) - timedelta(seconds=2),
        )
        assert get_current_user() is foreground_user
    finally:
        reset_current_user(user_token)

    # The foreground context and caller are gone. Recovery has only the owner
    # persisted in SQL; no original run or request credential is rehydrated.
    assert get_current_user() is None
    recovered_process = _service(repo, McpTaskToolCaller(config))
    if operation == "cancel":
        await recovered_process.cancel_task(task_id=created["id"], user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-1")
    await recovered_process.run_once(now=datetime.now(UTC))

    record = await repo.get(created["id"], user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-1")
    assert record is not None
    assert record["status"] == ("completed" if operation == "poll" else "cancelled")
    assert tool_names == ["submit_report", "status_report" if operation == "poll" else "cancel_report"]
    assert opened_headers == [{"Authorization": "Bearer task-owner"}] * 2
    assert get_current_user() is None


@pytest.mark.asyncio
@pytest.mark.no_auto_user
@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize(
    ("operation", "owner_can_access"),
    [("poll", True), ("cancel", True), ("poll", False)],
    ids=["poll-shared-task", "cancel-shared-task", "poll-task-not-found"],
)
async def test_recovered_task_with_request_and_user_credentials(tmp_path, monkeypatch, transport: str, operation: str, owner_can_access: bool) -> None:
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    repo = McpTaskRepository(session_factory)
    await _create_thread(repo)
    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": transport,
                    "url": "https://reports.example.com/mcp",
                    "headers": {"Authorization": "Bearer discovery"},
                    "user_auth": {"users": {"user-1": "Bearer task-owner"}},
                    "headers_from_context": {"headers": {"Authorization": "reports_token"}},
                    "task_toolsets": [{"name": "reports", "submit_tool": "submit_report", "status_tool": "status_report", "cancel_tool": "cancel_report"}],
                }
            }
        }
    )
    fake_server = FakeMcpServer()
    fake_server.status_results.append({"task_id": "remote-1", "status": "completed", "result": {"report": "ready"}})
    opened_headers = []
    tool_names = []

    @asynccontextmanager
    async def create_session(connection):
        opened_headers.append(dict(connection["headers"]))

        async def call_tool(name, arguments):
            tool_names.append(name)
            if connection["headers"]["Authorization"] == "Bearer task-owner" and not owner_can_access:
                return SimpleNamespace(structuredContent={"task_id": arguments["task_id"], "status": "failed", "error_code": "task_not_found"}, content=[], isError=False)
            return await fake_server.call_tool(tool_name=name, arguments=arguments)

        yield SimpleNamespace(initialize=AsyncMock(), call_tool=call_tool)

    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", create_session)
    first_process = _service(repo, McpTaskToolCaller(config))

    @tool
    async def submit_report() -> str:
        """Submit a durable report task."""
        created = await first_process.submit(
            driver_name=ORDINARY_MCP_TASK_DRIVER,
            request=_request("remote-1"),
            now=datetime.now(UTC) - timedelta(seconds=2),
        )
        return created["id"]

    builder = StateGraph(MessagesState, context_schema=dict)
    builder.add_node("tools", ToolNode([submit_report]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()
    user_token = set_current_user(SimpleNamespace(id="user-1"))
    try:
        submitted = await graph.ainvoke(
            {"messages": [AIMessage(content="", tool_calls=[{"name": "submit_report", "args": {}, "id": "call-1", "type": "tool_call"}])]},
            context={"user_id": "user-1", "secrets": {"reports_token": "Bearer request"}},
        )
    finally:
        reset_current_user(user_token)

    # The real graph supplied the submit secret. Its runtime and foreground
    # identity are no longer present when a new caller recovers the SQL task.
    assert get_current_user() is None
    task_id = submitted["messages"][-1].content
    recovered_process = _service(repo, McpTaskToolCaller(config))
    if operation == "cancel":
        await recovered_process.cancel_task(task_id=task_id, user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-1")
    await recovered_process.run_once(now=datetime.now(UTC))

    record = await repo.get(task_id, user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-1")
    assert record is not None
    if owner_can_access:
        assert record["status"] == ("completed" if operation == "poll" else "cancelled")
    else:
        assert record["status"] == "failed"
        assert record["error"] == "Remote MCP task was not found"
        assert record["next_poll_at"] is None
        assert record["consecutive_poll_error_count"] == 0
        await recovered_process.run_once(now=datetime.now(UTC) + timedelta(seconds=60))
    assert tool_names == ["submit_report", "status_report" if operation == "poll" else "cancel_report"]
    assert opened_headers == [{"Authorization": "Bearer request"}, {"Authorization": "Bearer task-owner"}]
    assert get_current_user() is None
