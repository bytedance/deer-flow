import asyncio
import sys
from collections.abc import Coroutine
from contextlib import suppress
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, ErrorData

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.mcp.session_pool import MCPSessionPool
from deerflow.mcp.task_tool_caller import McpTaskToolCaller, mcp_task_session_scope_key


def _config() -> ExtensionsConfig:
    return ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": "stdio",
                    "command": "report-mcp",
                    "task_toolsets": [
                        {
                            "name": "reports",
                            "submit_tool": "submit_report",
                            "status_tool": "status_report",
                            "cancel_tool": "cancel_report",
                        }
                    ],
                }
            }
        }
    )


def _remote_config(transport: str = "http") -> ExtensionsConfig:
    return ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": transport,
                    "url": "https://reports.example.com/mcp",
                    "headers": {"X-Static": "configured"},
                }
            }
        }
    )


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return None


async def _assert_configured_timeout(awaitable: Coroutine[Any, Any, Any]) -> None:
    task = asyncio.create_task(awaitable)
    try:
        done, _pending = await asyncio.wait({task}, timeout=0.25)
        assert task in done, "configured timeout was ignored"
        with pytest.raises(TimeoutError):
            await task
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def test_task_session_scope_includes_user_and_thread() -> None:
    assert mcp_task_session_scope_key(user_id="user-1", thread_id="thread-1") == "user-1:thread-1"


@pytest.mark.asyncio
async def test_stdio_task_call_reuses_exact_scope_and_raw_tool_name() -> None:
    result = SimpleNamespace(structuredContent={"task_id": "remote-1", "status": "running"}, isError=False)
    session = SimpleNamespace(call_tool=AsyncMock(return_value=result))
    pool = MagicMock()
    pool.get_session = AsyncMock(return_value=session)
    pool.close_session = AsyncMock()
    caller = McpTaskToolCaller(_config())

    with (
        patch("deerflow.mcp.task_tool_caller.get_session_pool", return_value=pool),
        patch(
            "deerflow.mcp.task_tool_caller._prepare_stdio_connection",
            return_value={"transport": "stdio", "command": "report-mcp"},
        ),
    ):
        actual = await caller.call_tool(
            server_name="reports",
            tool_name="status_report",
            arguments={"task_id": "remote-1"},
            user_id="user-1",
            thread_id="thread-1",
        )

    assert actual is result
    pool.get_session.assert_awaited_once_with(
        "reports",
        "user-1:thread-1",
        {"transport": "stdio", "command": "report-mcp"},
    )
    session.call_tool.assert_awaited_once_with("status_report", {"task_id": "remote-1"})
    pool.close_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "disconnect_error",
    [
        anyio.ClosedResourceError(),
        anyio.BrokenResourceError(),
        anyio.EndOfStream(),
        McpError(ErrorData(code=CONNECTION_CLOSED, message="Connection closed")),
    ],
)
async def test_broken_stdio_task_session_is_evicted_for_next_poll_reconnect(disconnect_error: Exception) -> None:
    session = SimpleNamespace(call_tool=AsyncMock(side_effect=disconnect_error))
    pool = MagicMock()
    pool.get_session = AsyncMock(return_value=session)
    pool.close_session = AsyncMock()
    pool.close_session_if_current = AsyncMock()
    caller = McpTaskToolCaller(_config())

    with (
        patch("deerflow.mcp.task_tool_caller.get_session_pool", return_value=pool),
        patch(
            "deerflow.mcp.task_tool_caller._prepare_stdio_connection",
            return_value={"transport": "stdio", "command": "report-mcp"},
        ),
        pytest.raises(type(disconnect_error)),
    ):
        await caller.call_tool(
            server_name="reports",
            tool_name="status_report",
            arguments={"task_id": "remote-1"},
            user_id="user-1",
            thread_id="thread-1",
        )

    pool.close_session_if_current.assert_awaited_once_with(
        "reports",
        "user-1:thread-1",
        session,
    )
    pool.close_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_stdio_task_timeout_keeps_healthy_stateful_session() -> None:
    timeout_error = McpError(ErrorData(code=408, message="request timed out"))
    session = SimpleNamespace(call_tool=AsyncMock(side_effect=timeout_error))
    pool = MagicMock()
    pool.get_session = AsyncMock(return_value=session)
    pool.close_session = AsyncMock()
    pool.close_session_if_current = AsyncMock()
    caller = McpTaskToolCaller(_config())

    with (
        patch("deerflow.mcp.task_tool_caller.get_session_pool", return_value=pool),
        patch(
            "deerflow.mcp.task_tool_caller._prepare_stdio_connection",
            return_value={"transport": "stdio", "command": "report-mcp"},
        ),
        pytest.raises(McpError, match="request timed out"),
    ):
        await caller.call_tool(
            server_name="reports",
            tool_name="status_report",
            arguments={"task_id": "remote-1"},
            user_id="user-1",
            thread_id="thread-1",
        )

    pool.close_session_if_current.assert_not_awaited()
    pool.close_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_stdio_task_interceptor_failure_keeps_healthy_session() -> None:
    session = SimpleNamespace(call_tool=AsyncMock())
    pool = MagicMock()
    pool.get_session = AsyncMock(return_value=session)
    pool.close_session = AsyncMock()
    pool.close_session_if_current = AsyncMock()
    caller = McpTaskToolCaller(_config())

    async def reject_call(_request, _handler):
        raise RuntimeError("interceptor rejected call")

    caller._interceptors = [reject_call]

    with (
        patch("deerflow.mcp.task_tool_caller.get_session_pool", return_value=pool),
        patch(
            "deerflow.mcp.task_tool_caller._prepare_stdio_connection",
            return_value={"transport": "stdio", "command": "report-mcp"},
        ),
        pytest.raises(RuntimeError, match="interceptor rejected call"),
    ):
        await caller.call_tool(
            server_name="reports",
            tool_name="status_report",
            arguments={"task_id": "remote-1"},
            user_id="user-1",
            thread_id="thread-1",
        )

    session.call_tool.assert_not_awaited()
    pool.close_session_if_current.assert_not_awaited()
    pool.close_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_stdio_task_timeout_preserves_real_stateful_session(tmp_path) -> None:
    server = """
import asyncio
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("slow-status")
tasks = {}


@mcp.tool()
def submit_report() -> dict[str, object]:
    tasks["remote-1"] = 0
    return {"task_id": "remote-1", "status": "running", "pid": os.getpid()}


@mcp.tool()
async def status_report(task_id: str) -> dict[str, object]:
    if task_id not in tasks:
        return {"task_id": task_id, "status": "failed", "error_code": "task_not_found"}
    tasks[task_id] += 1
    if tasks[task_id] == 1:
        await asyncio.sleep(0.2)
    return {
        "task_id": task_id,
        "status": "completed",
        "pid": os.getpid(),
        "status_calls": tasks[task_id],
    }


mcp.run(transport="stdio")
"""
    config = _config()
    server_config = config.mcp_servers["reports"]
    server_config.command = sys.executable
    server_config.args = ["-c", server]
    server_config.tool_call_timeout = 1.0
    caller = McpTaskToolCaller(config)
    pool = MCPSessionPool()

    try:
        with (
            patch("deerflow.mcp.task_tool_caller.get_paths", return_value=Paths(tmp_path)),
            patch("deerflow.mcp.task_tool_caller.get_session_pool", return_value=pool),
        ):
            submitted = await caller.call_tool(
                server_name="reports",
                tool_name="submit_report",
                arguments={},
                user_id="user-1",
                thread_id="thread-1",
            )

            server_config.tool_call_timeout = 0.05
            with pytest.raises(McpError, match="Timed out while waiting") as exc_info:
                await caller.call_tool(
                    server_name="reports",
                    tool_name="status_report",
                    arguments={"task_id": submitted.structuredContent["task_id"]},
                    user_id="user-1",
                    thread_id="thread-1",
                )
            assert exc_info.value.error.code == 408

            await asyncio.sleep(0.25)
            server_config.tool_call_timeout = 1.0
            recovered = await caller.call_tool(
                server_name="reports",
                tool_name="status_report",
                arguments={"task_id": submitted.structuredContent["task_id"]},
                user_id="user-1",
                thread_id="thread-1",
            )
    finally:
        await pool.close_all()

    assert recovered.structuredContent == {
        "task_id": "remote-1",
        "status": "completed",
        "pid": submitted.structuredContent["pid"],
        "status_calls": 2,
    }


@pytest.mark.asyncio
async def test_stdio_task_session_initialization_respects_configured_timeout() -> None:
    config = _config()
    config.mcp_servers["reports"].session_init_timeout = 0.01

    async def slow_get_session(*_args):
        await asyncio.sleep(60)

    pool = MagicMock()
    pool.get_session = AsyncMock(side_effect=slow_get_session)
    pool.close_session = AsyncMock()
    caller = McpTaskToolCaller(config)

    with (
        patch("deerflow.mcp.task_tool_caller.get_session_pool", return_value=pool),
        patch(
            "deerflow.mcp.task_tool_caller._prepare_stdio_connection",
            return_value={"transport": "stdio", "command": "report-mcp"},
        ),
        pytest.raises(TimeoutError),
    ):
        await caller.call_tool(
            server_name="reports",
            tool_name="status_report",
            arguments={"task_id": "remote-1"},
            user_id="user-1",
            thread_id="thread-1",
        )

    pool.close_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_task_call_authenticates_session_initialization() -> None:
    result = SimpleNamespace(structuredContent={"task_id": "remote-1", "status": "running"}, isError=False)
    session = SimpleNamespace(
        initialize=AsyncMock(),
        call_tool=AsyncMock(return_value=result),
    )
    create_session = MagicMock(return_value=_SessionContext(session))
    caller = McpTaskToolCaller(
        _remote_config(),
        oauth_token_manager=SimpleNamespace(
            has_oauth_servers=lambda: False,
            get_authorization_header=AsyncMock(return_value="Bearer task-token"),
        ),
    )

    with patch(
        "langchain_mcp_adapters.sessions.create_session",
        create_session,
    ):
        actual = await caller.call_tool(
            server_name="reports",
            tool_name="status_report",
            arguments={"task_id": "remote-1"},
            user_id="user-1",
            thread_id="thread-1",
        )

    assert actual is result
    create_session.assert_called_once_with(
        {
            "transport": "http",
            "url": "https://reports.example.com/mcp",
            "headers": {
                "X-Static": "configured",
                "Authorization": "Bearer task-token",
            },
        }
    )
    session.initialize.assert_awaited_once_with()
    session.call_tool.assert_awaited_once_with(
        "status_report",
        {"task_id": "remote-1"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
async def test_remote_task_session_initialization_respects_configured_timeout(transport: str) -> None:
    config = _remote_config(transport)
    config.mcp_servers["reports"].session_init_timeout = 0.01

    async def slow_initialize():
        await asyncio.sleep(60)

    session = SimpleNamespace(
        initialize=AsyncMock(side_effect=slow_initialize),
        call_tool=AsyncMock(),
    )
    caller = McpTaskToolCaller(
        config,
        oauth_token_manager=SimpleNamespace(
            has_oauth_servers=lambda: False,
            get_authorization_header=AsyncMock(return_value=None),
        ),
    )

    with patch(
        "langchain_mcp_adapters.sessions.create_session",
        MagicMock(return_value=_SessionContext(session)),
    ):
        await _assert_configured_timeout(
            caller.call_tool(
                server_name="reports",
                tool_name="status_report",
                arguments={"task_id": "remote-1"},
                user_id="user-1",
                thread_id="thread-1",
            )
        )

    session.call_tool.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
async def test_remote_task_call_respects_configured_timeout(transport: str) -> None:
    config = _remote_config(transport)
    config.mcp_servers["reports"].tool_call_timeout = 0.01

    async def slow_call(*_args, **_kwargs):
        await asyncio.sleep(60)

    session = SimpleNamespace(
        initialize=AsyncMock(),
        call_tool=AsyncMock(side_effect=slow_call),
    )
    caller = McpTaskToolCaller(
        config,
        oauth_token_manager=SimpleNamespace(
            has_oauth_servers=lambda: False,
            get_authorization_header=AsyncMock(return_value=None),
        ),
    )

    with patch(
        "langchain_mcp_adapters.sessions.create_session",
        MagicMock(return_value=_SessionContext(session)),
    ):
        await _assert_configured_timeout(
            caller.call_tool(
                server_name="reports",
                tool_name="status_report",
                arguments={"task_id": "remote-1"},
                user_id="user-1",
                thread_id="thread-1",
            )
        )

    session.call_tool.assert_awaited_once_with(
        "status_report",
        {"task_id": "remote-1"},
        read_timeout_seconds=timedelta(seconds=0.01),
    )
