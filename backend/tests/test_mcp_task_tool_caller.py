import asyncio
import sys
from collections.abc import Coroutine
from contextlib import asynccontextmanager, suppress
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
from deerflow.mcp.task_tool_caller import McpTaskToolCaller
from deerflow.mcp_scope import mcp_session_scope_key


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


def _remote_status_call(config: ExtensionsConfig) -> Coroutine[Any, Any, Any]:
    return McpTaskToolCaller(config).call_tool(
        server_name="reports",
        tool_name="status_report",
        arguments={"task_id": "remote-1"},
        user_id="user-1",
        thread_id="thread-1",
    )


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return None


async def _assert_configured_timeout(awaitable: Coroutine[Any, Any, Any], *, wait_timeout: float = 0.25, expected_message: str | None = None) -> None:
    task = asyncio.create_task(awaitable)
    try:
        done, _pending = await asyncio.wait({task}, timeout=wait_timeout)
        assert task in done, "configured timeout was ignored"
        with pytest.raises(TimeoutError) as error:
            await task
        if expected_message is not None:
            assert str(error.value) == expected_message
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def test_task_session_scope_includes_user_thread_and_incarnation() -> None:
    first = mcp_session_scope_key(user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-1")
    second = mcp_session_scope_key(user_id="user-1", thread_id="thread-1", thread_incarnation="incarnation-2")

    assert first == 'v2:["user-1","thread-1","incarnation-1"]'
    assert second == 'v2:["user-1","thread-1","incarnation-2"]'
    assert first != second
    assert mcp_session_scope_key(user_id="a:b", thread_id="c", thread_incarnation="d") != mcp_session_scope_key(
        user_id="a",
        thread_id="b:c",
        thread_incarnation="d",
    )
    assert mcp_session_scope_key(user_id="user-1", thread_id="thread-1", thread_incarnation=None) == "user-1:thread-1"
    with pytest.raises(RuntimeError, match="non-empty"):
        mcp_session_scope_key(user_id="user-1", thread_id="thread-1", thread_incarnation="")


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
            thread_incarnation=None,
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
            thread_incarnation=None,
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
            thread_incarnation=None,
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
            thread_incarnation=None,
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
                thread_incarnation=None,
            )

            server_config.tool_call_timeout = 0.05
            with pytest.raises(McpError, match="Timed out while waiting") as exc_info:
                await caller.call_tool(
                    server_name="reports",
                    tool_name="status_report",
                    arguments={"task_id": submitted.structuredContent["task_id"]},
                    user_id="user-1",
                    thread_id="thread-1",
                    thread_incarnation=None,
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
                thread_incarnation=None,
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
            thread_incarnation=None,
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
            thread_incarnation=None,
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
            expected_message="MCP task session initialization for server 'reports' timed out after 0.01s",
            awaitable=caller.call_tool(
                server_name="reports",
                tool_name="status_report",
                arguments={"task_id": "remote-1"},
                user_id="user-1",
                thread_id="thread-1",
                thread_incarnation=None,
            ),
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
            expected_message="",
            awaitable=caller.call_tool(
                server_name="reports",
                tool_name="status_report",
                arguments={"task_id": "remote-1"},
                user_id="user-1",
                thread_id="thread-1",
                thread_incarnation=None,
            ),
        )

    session.call_tool.assert_awaited_once_with(
        "status_report",
        {"task_id": "remote-1"},
        read_timeout_seconds=timedelta(seconds=0.01),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize("phase", ["connect", "initialize", "call", "cleanup"])
async def test_remote_task_unrelated_timeout_is_not_relabelled(transport: str, phase: str) -> None:
    config = _remote_config(transport)
    config.mcp_servers["reports"].session_init_timeout = 1.0
    original = TimeoutError(f"original {phase} timeout")
    session = SimpleNamespace(initialize=AsyncMock(), call_tool=AsyncMock(return_value={"ok": True}))
    if phase == "initialize":
        session.initialize.side_effect = original
    elif phase == "call":
        session.call_tool.side_effect = original

    @asynccontextmanager
    async def fake_session(_connection):
        if phase == "connect":
            raise original
        yield session
        if phase == "cleanup":
            raise original

    with patch("langchain_mcp_adapters.sessions.create_session", fake_session):
        with pytest.raises(TimeoutError) as error:
            await _remote_status_call(config)
    assert error.value is original


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
async def test_remote_task_session_open_respects_configured_timeout(transport: str) -> None:
    config = _remote_config(transport)
    config.mcp_servers["reports"].session_init_timeout = 0.01
    session = SimpleNamespace(initialize=AsyncMock(), call_tool=AsyncMock())
    closed = asyncio.Event()

    @asynccontextmanager
    async def slow_session(_connection):
        try:
            async with anyio.create_task_group():
                await asyncio.Event().wait()
                yield session
        finally:
            closed.set()

    with patch("langchain_mcp_adapters.sessions.create_session", slow_session):
        await _assert_configured_timeout(expected_message="MCP task session initialization for server 'reports' timed out after 0.01s", awaitable=_remote_status_call(config))

    assert closed.is_set()
    session.initialize.assert_not_awaited()
    session.call_tool.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
async def test_remote_task_connection_and_initialize_share_timeout(transport: str) -> None:
    config = _remote_config(transport)
    config.mcp_servers["reports"].session_init_timeout = 0.5

    async def slow_initialize():
        await asyncio.sleep(0.3)

    session = SimpleNamespace(initialize=AsyncMock(side_effect=slow_initialize), call_tool=AsyncMock())

    @asynccontextmanager
    async def slow_session(_connection):
        async with anyio.create_task_group():
            await asyncio.sleep(0.3)
            yield session

    with patch("langchain_mcp_adapters.sessions.create_session", slow_session):
        await _assert_configured_timeout(expected_message="MCP task session initialization for server 'reports' timed out after 0.5s", awaitable=_remote_status_call(config), wait_timeout=2)

    session.initialize.assert_awaited_once()
    session.call_tool.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize("init_timeout", [None, 0.01])
async def test_remote_task_initialization_timeout_does_not_limit_tool_call(transport: str, init_timeout: float | None) -> None:
    config = _remote_config(transport)
    config.mcp_servers["reports"].session_init_timeout = init_timeout
    config.mcp_servers["reports"].tool_call_timeout = 1.0
    result = SimpleNamespace(structuredContent={"status": "completed"}, isError=False)
    closed = asyncio.Event()

    async def slow_call(*_args, **_kwargs):
        await asyncio.sleep(0.04)
        return result

    session = SimpleNamespace(initialize=AsyncMock(), call_tool=AsyncMock(side_effect=slow_call))

    @asynccontextmanager
    async def task_group_session(_connection):
        owner = asyncio.current_task()
        async with anyio.create_task_group():
            try:
                yield session
            finally:
                assert asyncio.current_task() is owner
                closed.set()

    with patch("langchain_mcp_adapters.sessions.create_session", task_group_session):
        assert await _remote_status_call(config) is result

    assert closed.is_set()
    session.call_tool.assert_awaited_once_with("status_report", {"task_id": "remote-1"}, read_timeout_seconds=timedelta(seconds=1))


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize("phase", ["connect", "initialize", "call"])
async def test_remote_task_session_preserves_external_cancellation(transport: str, phase: str) -> None:
    config = _remote_config(transport)
    reached = asyncio.Event()
    closed = asyncio.Event()

    async def pause_at(current_phase):
        if current_phase == phase:
            reached.set()
            await asyncio.Event().wait()

    async def initialize():
        await pause_at("initialize")

    async def call_tool(*_args, **_kwargs):
        await pause_at("call")

    session = SimpleNamespace(initialize=AsyncMock(side_effect=initialize), call_tool=AsyncMock(side_effect=call_tool))

    @asynccontextmanager
    async def task_group_session(_connection):
        owner = asyncio.current_task()
        try:
            async with anyio.create_task_group():
                await pause_at("connect")
                yield session
        finally:
            assert asyncio.current_task() is owner
            closed.set()

    with patch("langchain_mcp_adapters.sessions.create_session", task_group_session):
        task = asyncio.create_task(_remote_status_call(config))
        try:
            await asyncio.wait_for(reached.wait(), 1)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=1)
            assert task in done, "external cancellation did not finish session cleanup"
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed.is_set()
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["endpoint", "initialize"])
async def test_sse_task_session_timeout_closes_real_connection(monkeypatch, phase: str) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    connected = asyncio.Event()
    initialized = asyncio.Event()
    disconnected = asyncio.Event()
    handlers: set[asyncio.Task] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        handlers.add(asyncio.current_task())
        is_sse = False
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            is_sse = request.startswith(b"GET /sse ")
            if is_sse:
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n: connected\n\n")
                if phase == "initialize":
                    writer.write(b"event: endpoint\ndata: /messages/\n\n")
                await writer.drain()
                connected.set()
                await reader.read()
            else:
                assert request.startswith(b"POST /messages/ ")
                for header in request.split(b"\r\n"):
                    if header.lower().startswith(b"content-length:"):
                        await reader.readexactly(int(header.split(b":", 1)[1]))
                        break
                writer.write(b"HTTP/1.1 202 Accepted\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
                initialized.set()
        finally:
            writer.close()
            await writer.wait_closed()
            if is_sse:
                disconnected.set()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    config = _remote_config("sse")
    config.mcp_servers["reports"].url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/sse"
    config.mcp_servers["reports"].session_init_timeout = 0.5
    try:
        await _assert_configured_timeout(expected_message="MCP task session initialization for server 'reports' timed out after 0.5s", awaitable=_remote_status_call(config), wait_timeout=3)
        assert connected.is_set()
        assert initialized.is_set() == (phase == "initialize")
        await asyncio.wait_for(disconnected.wait(), 1)
    finally:
        server.close()
        for handler in handlers:
            if not handler.done():
                handler.cancel()
        results = await asyncio.gather(*handlers, return_exceptions=True)
        await server.wait_closed()
        assert all(not isinstance(result, BaseException) or isinstance(result, asyncio.CancelledError) for result in results), results
